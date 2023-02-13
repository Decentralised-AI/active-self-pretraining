from datautils.target_dataset import get_target_pretrain_ds
from models.active_learning.pretext_dataloader import PretextDataLoader
from models.active_learning.pretext_trainer import PretextTrainer
from models.backbones.resnet import resnet_backbone
from models.self_sup.swav.swav import SwAVTrainer
from models.trainers.base_pretrainer import BasePretrainer
from models.utils.commons import get_params
import utils.logger as logging
from models.self_sup.myow.trainer.myow_trainer import get_myow_trainer
from models.self_sup.simclr.trainer.simclr_trainer import SimCLRTrainer
from models.self_sup.simclr.trainer.simclr_trainer_v2 import SimCLRTrainerV2
from models.utils.training_type_enum import TrainingType
from utils.commons import load_path_loss, save_state
from models.utils.ssl_method_enum import SSL_Method


class SelfSupPretrainer(BasePretrainer):
    def __init__(self, 
        args, 
        writer) -> None:

        self.args = args
        self.writer = writer

    def base_pretrain(self, encoder, train_loader, epochs, trainingType) -> None:
        train_params = get_params(self.args, trainingType)
        
        pretrain_level = "1" if trainingType == TrainingType.BASE_PRETRAIN else "2"        
        logging.info(f"{trainingType.value} pretraining in progress, please wait...")

        log_step = self.args.log_step
        if self.args.method == SSL_Method.SIMCLR.value:
            trainer = SimCLRTrainer(
                self.args, self.writer, 
                encoder, train_loader, 
                pretrain_level=pretrain_level, 
                training_type=trainingType, 
                log_step=log_step
            )

        elif self.args.method == SSL_Method.DCL.value:
            trainer = SimCLRTrainerV2(
                self.args, self.writer, 
                encoder, train_loader, 
                pretrain_level=pretrain_level, 
                training_type=trainingType, 
                log_step=log_step
            )

        elif self.args.method == SSL_Method.SWAV.value:
            trainer = SwAVTrainer(
                self.args, train_loader, 
                pretrain_level=pretrain_level, 
                training_type=trainingType, 
                log_step=log_step
            )

        elif self.args.method == SSL_Method.MYOW.value:
            trainer = get_myow_trainer(
                self.args, self.writer, 
                encoder, train_loader, 
                pretrain_level=pretrain_level, 
                trainingType=trainingType, 
                log_step=log_step
            )

        else:
            ValueError

        model = trainer.model
        optimizer = trainer.optimizer

        self.args.current_epoch = 0
        for epoch in range(epochs):
            logging.info('\nEpoch {}/{}'.format(epoch, epochs))
            logging.info('-' * 20)

            epoch_loss = trainer.train_epoch(epoch)

            lr = 0
            # Decay Learning Rate
            if self.args.method is not SSL_Method.SWAV.value and trainer.scheduler:
                trainer.scheduler.step()
                lr = trainer.scheduler.get_last_lr()

            if epoch > 1 and epoch % epochs//2 == 0:
                save_state(self.args, model, optimizer, pretrain_level, train_params.optimizer)

            self.args.current_epoch += 1

        save_state(self.args, model, optimizer, pretrain_level, train_params.optimizer)


    def first_pretrain(self) -> None:
        encoder, train_loader = super().first_pretrain()
        
        self.base_pretrain(encoder, train_loader, self.args.base_epochs, trainingType=TrainingType.BASE_PRETRAIN)


    def second_pretrain(self) -> None:
        if self.args.do_al:
            pretrain_data = load_path_loss(self.args, self.args.pretrain_path_loss_file)
            if pretrain_data is None:
                pretext = PretextTrainer(self.args, self.writer)
                pretrain_data = pretext.do_active_learning()

            loader = PretextDataLoader(self.args, pretrain_data, training_type=TrainingType.TARGET_PRETRAIN).get_loader()
        else:
            loader = get_target_pretrain_ds(self.args, training_type=TrainingType.TARGET_PRETRAIN).get_loader()        

        encoder = resnet_backbone(self.args.backbone, pretrained=False)


        self.base_pretrain(encoder, loader, self.args.target_epochs, trainingType=TrainingType.TARGET_PRETRAIN)