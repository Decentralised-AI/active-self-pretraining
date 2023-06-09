import argparse
import os, sys
from os import path
import time
import copy
import torch
from torch import nn
import numpy as np
import random
# from torchsummary import summary
import shutil
import scipy.io as sio

def seed_torch(seed=1029):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)  # if you are using multi-GPU.
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


seed_torch(999)


from models.gan2 import utils
from models.gan2.train import Trainer, update_average
from models.gan2.toggle_ImageNet import toggle_grad_G, toggle_grad_D
from models.gan2.logger import Logger
from models.gan2.checkpoints import CheckpointIO
from models.gan2.inputs import get_dataset
from models.gan2.distributions import get_ydist, get_zdist
from models.gan2.eval import Evaluator
from models.gan2.config import (
    load_config, build_models, build_optimizers, build_lr_scheduler, build_models_PRE,
)
import logging

def info(message: str):
    print(message)
    logging.info(message)

def get_parameter_number(net):
    total_num = sum(p.numel() for p in net.parameters())
    trainable_num = sum(p.numel() for p in net.parameters() if p.requires_grad)
    print('Total=', total_num, 'Trainable=', trainable_num, 'fixed=', total_num-trainable_num)


def load_part_model(m_fix, m_ini):
    dict_fix = m_fix.state_dic()
    dict_ini = m_ini.state_dic()

    dict_fix = {k: v for k, v in dict_fix.items() if k in dict_ini and k.find('embedding')==-1 and k.find('fc') == -1}
    dict_ini.update(dict_fix)
    m_ini.load_state_dict(dict_ini)
    return m_ini


def model_equal_all(model, dict):
    model_dict = model.state_dict()
    model_dict.update(dict)
    model.load_state_dict(model_dict)
    return model


def model_equal_part(model, dict_all):
    model_dict = model.state_dict()
    dict_fix = {k: v for k, v in dict_all.items() if k in model_dict and k.find('embedding') == -1 and k.find('fc') == -1}
    model_dict.update(dict_fix)
    model.load_state_dict(model_dict)
    return model


''' ===================--- Set the traning mode ---==========================
DATA: going to train
DATA_FIX: used as a fixed pre-trained model
G_Layer_FIX, D_Layer_FIX: number of layers to fix
============================================================================='''

def main():
    DATA = 'Flowers'
    main_path = ''#'../../'

    image_path = main_path + 'datasets/face' #'datasets/102flowers/'
    is_control_kernel = True

    DATA_FIX = 'ImageNet'
    epochs = 500# *10000

    load_dir = main_path + 'pretrained_model/'
    out_path = 'save/generated'

    config_path = main_path + 'config/' +DATA+ '.yaml'

    G_Layer_FIX = -4
    D_Layer_FIX = 2

    config = load_config(config_path, main_path + 'config/default.yaml')

    config['generator']['layers'] = G_Layer_FIX
    config['discriminator']['layers'] = D_Layer_FIX
    config['data']['train_dir'] = image_path
    config['data']['test_dir'] = image_path

    config['generator']['name'] = 'resnet2_AdaFM'
    config['discriminator']['name'] = 'resnet2_AdaFM'

    config['training']['out_dir'] = out_path
    if not os.path.isdir(config['training']['out_dir']):
        os.makedirs(config['training']['out_dir'])

    # Short hands
    batch_size = config['training']['batch_size']
    d_steps = config['training']['d_steps']
    restart_every = config['training']['restart_every']
    inception_every = config['training']['inception_every']
    save_every = config['training']['save_every']
    backup_every = config['training']['backup_every']
    sample_nlabels = config['training']['sample_nlabels']

    out_dir = config['training']['out_dir']
    checkpoint_dir = path.join(out_dir, 'chkpts')

    # Create missing directories
    if not path.exists(out_dir):
        os.makedirs(out_dir)
    if not path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)
    shutil.copyfile(sys.argv[0], out_dir + '/training_script.py')

    # Logger
    checkpoint_io = CheckpointIO(
        checkpoint_dir=checkpoint_dir
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Dataset
    train_dataset, nlabels = get_dataset(
        name=config['data']['type'],
        data_dir=config['data']['train_dir'],
        size=config['data']['img_size'],
        lsun_categories=config['data']['lsun_categories_train']
    )
    train_loader = torch.utils.data.DataLoader(
            # train_dataset,
            [data for data in  train_dataset],
            batch_size=batch_size,
            num_workers=config['training']['nworkers'],
            shuffle=True, pin_memory=True, sampler=None, drop_last=True
    )

    # Number of labels
    nlabels = min(nlabels, config['data']['nlabels'])
    sample_nlabels = min(nlabels, sample_nlabels)





    # Create models
    ''' --------- Choose the fixed layer ---------------'''
    generator, discriminator = build_models(config)

    if os.path.exists(load_dir + DATA_FIX):
        info("Using saved models...")
        
        dict_G = torch.load(load_dir + DATA_FIX + 'Pre_generator')
        generator = model_equal_part(generator, dict_G)
        dict_D = torch.load(load_dir + DATA_FIX + 'Pre_discriminator')
        discriminator = model_equal_part(discriminator, dict_D)

    for name, param in generator.named_parameters():
        if name.find('small') >= 0:
            param.requires_grad = True
        else:
            param.requires_grad = False
        if name.find('small_adafm_') >= 0:
            param.requires_grad = False
    get_parameter_number(generator)

    for param in discriminator.parameters():
        param.requires_grad = False

    #toggle_grad_G(generator, True, G_Layer_FIX)
    toggle_grad_D(discriminator, True, D_Layer_FIX)

    # Put models on gpu if needed
    generator, discriminator = generator.to(device), discriminator.to(device)
    g_optimizer, d_optimizer = build_optimizers(generator, discriminator, config)

    # Register modules to checkpoint
    checkpoint_io.register_modules(
        generator=generator,
        discriminator=discriminator,
        g_optimizer=g_optimizer,
        d_optimizer=d_optimizer,
    )

    # Logger
    logger = Logger(
        log_dir=path.join(out_dir, 'logs'),
        img_dir=path.join(out_dir, 'imgs'),
        monitoring=config['training']['monitoring'],
        monitoring_dir=path.join(out_dir, 'monitoring')
    )

    # Distributions
    ydist = get_ydist(nlabels, device=device)
    zdist = get_zdist(config['z_dist']['type'], config['z_dist']['dim'],
                        device=device)

    # Save for tests
    ntest = 16 #100
    x_real, ytest = utils.get_nsamples(train_loader, ntest)
    ytest.clamp_(None, nlabels-1)
    ytest = ytest.to(device)
    ztest = zdist.sample((ntest,)).to(device)
    utils.save_images(x_real, path.join(out_dir, 'real.png'))

    # Test generator
    if config['training']['take_model_average']:
        generator_test = copy.deepcopy(generator)
        checkpoint_io.register_modules(generator_test=generator_test)
    else:
        generator_test = generator

    # Evaluator

    NNN = 251 #8000
    x_real, _ = utils.get_nsamples(train_loader, NNN)
    evaluator = Evaluator(generator_test, zdist, ydist,
                            batch_size=batch_size, device=device,
                            fid_real_samples=x_real, inception_nsamples=NNN, fid_sample_size=NNN)
    # Train
    tstart = t0 = time.time()

    # Reinitialize model average if needed
    if (config['training']['take_model_average']
            and config['training']['model_average_reinit']):
        update_average(generator_test, generator, 0.)

    # Learning rate anneling
    g_scheduler = build_lr_scheduler(g_optimizer, config)
    d_scheduler = build_lr_scheduler(d_optimizer, config)

    # Trainer
    trainer = Trainer(
        generator, discriminator, g_optimizer, d_optimizer,
        gan_type=config['training']['gan_type'],
        reg_type=config['training']['reg_type'],
        reg_param=config['training']['reg_param'],
        D_fix_layer=config['discriminator']['layers']
    )


    # Training loop
    info(f'Training starts: Dataset size = {len(train_dataset)}, Iterations per epoch (batches) = {train_loader.__len__()}, Epochs = {epochs}')
    save_dir = config['training']['out_dir'] + '/models/'
    if not os.path.isdir(save_dir):
        os.makedirs(save_dir)
    FLAG = 500

    inception_mean_all = []
    inception_std_all = []
    fid_all = []

    for epoch in range(epochs):
        info('\nEpoch {}/{}'.format(epoch, epochs))
        info('-' * 20)

        for step, (x_real, y) in enumerate(train_loader):        
            dlr = d_optimizer.param_groups[0]['lr']
            glr = g_optimizer.param_groups[0]['lr']

            x_real, y = x_real.to(device), y.to(device)
            y.clamp_(None, nlabels-1)

            # Generators updates
            z = zdist.sample((batch_size,))
            gloss, x_fake = trainer.generator_trainstep(y, z, FLAG + 1.0)
            FLAG = FLAG * 0.9995

            if config['training']['take_model_average']:
                update_average(generator_test, generator, beta=config['training']['model_average_beta'])

            # Discriminator updates
            dloss, reg = trainer.discriminator_trainstep(x_real, y, x_fake)

            if is_control_kernel:
                if step == 10000:
                    for name, param in generator.named_parameters():
                        if name.find('small_adafm_') >= 0:
                            param.requires_grad = True
                    get_parameter_number(generator)

            g_scheduler.step()
            d_scheduler.step()

            with torch.no_grad():
                # (i) Sample if necessary
                if (step % config['training']['sample_every']) == 0:
                    d_fix, d_update = discriminator.conv_img.weight[1, 1, 1, 1], discriminator.fc.weight[0, 1]
                    g_fix, g_update = generator.conv_img.weight[1, 1, 1, 1], 0.0

                    info(
                        "Epoch: [{0}][{1}]\t"
                        "Loss - G|D: {gloss:.4f} | {dloss:.4f}\t"
                        "Reg {reg:.4f}\t"
                        "Lr - G|D: {glr:.4f} | {dlr:.4f}".format(
                            epoch, step,
                            gloss=gloss,
                            dloss=dloss,
                            reg=reg,
                            glr=glr,
                            dlr=dlr
                        )
                    )

                # (iii) Backup if necessary
                if ((step + 1) % backup_every) == 0:
                        print('Saving backup...')

                        TrainModeSave = DATA + '_%08d_' % step
                        torch.save(generator_test.state_dict(), save_dir + TrainModeSave + 'Pre_generator')
                        torch.save(discriminator.state_dict(), save_dir + TrainModeSave + 'Pre_discriminator')

    info('Creating samples...')
    x, _ = evaluator.create_samples(ztest, ytest)
    logger.add_imgs(x, 'all', step, nrow=10)


if __name__ == "__main__":
    main()


