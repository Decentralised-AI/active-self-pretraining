import os
import numpy as np
import torch
import torch.nn as nn
import torchvision
import argparse

# import cv2
from torch.utils.tensorboard import SummaryWriter
from datautils.dataset_enum import get_dataset_enum
from models.active_learning.pretext_trainer import PretextTrainer
from utils.commons import load_path_loss, load_saved_state, simple_load_model
from utils.random_seeders import set_random_seeds

from utils.yaml_config_hook import yaml_config_hook
from models.trainers.selfsup_pretrainer import SelfSupPretrainer
from models.trainers.sup_pretrainer import SupPretrainer
from models.trainers.classifier import Classifier
from models.trainers.classifier2 import Classifier2
import utils.logger as logging
# import logging

from models.gan5.train import do_gen_ai

logging.init()

def main(args):
    writer = SummaryWriter()

    if args.ml_project:
        state = load_saved_state(args, pretrain_level="1")
        if not state:
            pretrainer = SelfSupPretrainer(args, writer)
            # pretrainer = SupPretrainer(args, writer)
            pretrainer.first_pretrain()

        if args.do_al_for_ml_project:
            pretext = PretextTrainer(args, writer)
            pretrain_data = pretext.do_active_learning()

        else: 
            classifier = Classifier(args, writer, pretrain_level="1")
            classifier.train_and_eval() 

    else:
        if args.base_pretrain:
            do_gen_ai()

        #     pretrainer = SelfSupPretrainer(args, writer)
        #     pretrainer.first_pretrain()

        # if args.target_pretrain:
        #     pretrainer = SelfSupPretrainer(args, writer)
        #     pretrainer.second_pretrain()

        # classifier = Classifier(args, pretrain_level="2")
        # classifier.train_and_eval()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CASL")
    config = yaml_config_hook("./config/config.yaml")
    for k, v in config.items():
        parser.add_argument(f"--{k}", default=v, type=type(v))

    args = parser.parse_args()

    args.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print(f"You are using {args.device}")
    args.num_gpus = torch.cuda.device_count()
    args.world_size = args.gpus * args.nodes

    args.epoch_num = args.base_epochs
    args.target_epoch_num = args.target_epochs

    set_random_seeds(random_seed=args.seed)

    assert args.target_dataset == args.lc_dataset
    assert args.base_dataset == args.target_dataset

    args.base_dataset = f'generated_{get_dataset_enum(args.base_dataset)}'

    main(args)

    logging.info("CASL ended.")

