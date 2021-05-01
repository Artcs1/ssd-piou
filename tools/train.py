import os
import sys
sys.path.append(os.getcwd())
from model import build_ssd
from data import *
from config import crack
from utils import MultiBoxLoss


import time
import torch
import torch.nn as nn
import torch.optim as optim
import torch.backends.cudnn as cudnn
import torch.nn.init as init
import torch.utils.data as data

import argparse
from tqdm import tqdm
import numpy as np

def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")
'''
from eval import test_net
'''
parser = argparse.ArgumentParser(description=
    'Single Shot MultiBox Detector Training With Pytorch')
train_set = parser.add_mutually_exclusive_group()
parser.add_argument('--dataset', default='VOC', choices=['VOC', 'COCO','CRACK','TRAFIC'],
                    type=str, help='VOC or COCO')
parser.add_argument('--basenet', default=None,#'vgg16_reducedfc.pth',
                    help='Pretrained base model')
parser.add_argument('--batch_size', default=32, type=int,
                    help='Batch size for training')
parser.add_argument('--max_epoch', default=220, type=int,
                    help='Max Epoch for training')
parser.add_argument('--resume', default=None, type=str,
                    help='Checkpoint state_dict file to resume training from')
parser.add_argument('--start_iter', default=0, type=int,
                    help='Resume training at this iter')
parser.add_argument('--num_workers', default=2, type=int,
                    help='Number of workers used in dataloading')
parser.add_argument('--cuda', default=True, type=str2bool,
                    help='Use CUDA to train model')
parser.add_argument('--lr', '--learning-rate', default=1e-3, type=float,
                    help='initial learning rate')
parser.add_argument('--momentum', default=0.9, type=float,
                    help='Momentum value for optim')
parser.add_argument('--weight_decay', default=5e-4, type=float,
                    help='Weight decay for SGD')
parser.add_argument('--gamma', default=0.1, type=float,
                    help='Gamma update for SGD')
parser.add_argument('--visdom', default='VOC',type=str,
                    help='Use visdom')
parser.add_argument('--work_dir', default='work_dir/',
                    help='Directory for saving checkpoint models')

parser.add_argument('--weight', default=5, type=int)

parser.add_argument("--loss",default="Iou",type=str)
parser.add_argument("--work_name",default="SSD300_VOC_FPN_IOU",type=str)

args = parser.parse_args()

weight = args.weight

if torch.cuda.is_available():
    if args.cuda:
        torch.set_default_tensor_type('torch.cuda.FloatTensor')
    if not args.cuda:
        print("WARNING: It looks like you have a CUDA device, but aren't " +
              "using CUDA.\nRun with --cuda for optimal training speed.")
        torch.set_default_tensor_type('torch.FloatTensor')
else:
    torch.set_default_tensor_type('torch.FloatTensor')

if not os.path.exists(args.work_dir):
    os.mkdir(args.work_dir)

voc= {
    'model':"resnet50",
    'losstype':args.loss,
    'num_classes':21,
    'mean':(123.675, 116.28, 103.53),
    'std':(1.0,1.0,1.0),#(58.395, 57.12, 57.375),
    'lr_steps': (80000, 100000,120000),
    'max_iter': 120000,
    'max_epoch': 80,
    'feature_maps': [38, 19, 10, 5, 3, 1],
    'min_dim': 300,
    'backbone_out':[512,1024,2048,512,256,256],
    'neck_out':[256,256,256,256,256,256],
    'steps':[8, 16, 32, 64, 100, 300],
    'min_sizes': [30, 60, 111, 162, 213, 264],
    'max_sizes': [60, 111, 162, 213, 264, 315],
    'aspect_ratios': [[2], [2, 3], [2, 3], [2, 3], [2], [2]],
    'variance': [0.1, 0.2],
    'clip': True, 
    'nms_kind': "greedynms",       #Currently, NMS only surports 'cluster_nms', 'cluster_diounms', 'cluster_weighted_nms', 'cluster_weighted_diounms'
    'beta1':0.5,
    'name': 'VOC',
    'work_name':args.work_name,
}





def data_eval(dataset, net):
    return test_net('eval/', net, True, dataset,
             BaseTransform(trafic['min_dim'], MEANS), 5, 300,
             thresh=0.05)


def train():
    '''
    get the dataset and dataloader
    '''
    print(args.dataset)
    if args.dataset == 'COCO':
        if not os.path.exists(COCO_ROOT):
            parser.error('Must specify dataset_root if specifying dataset')

        cfg = coco
        dataset = COCODetection(root=COCO_ROOT,
                                transform=SSDAugmentation(cfg['min_dim'],
                                                          MEANS),filename = 'train.txt')
    elif args.dataset == 'VOC':
        if not os.path.exists(VOC_ROOT):
            parser.error('Must specify dataset_root if specifying dataset')

        cfg = voc
        dataset = VOCDetection(root=VOC_ROOT,
                               transform = SSDAugmentation(cfg['min_dim'],
                                mean = cfg['mean'],std = cfg['std']))
        valid_dataset = VOCDetection(root=VOC_ROOT, image_sets=[('2007', 'val')], transform = SSDAugmentation(cfg['min_dim'],mean = cfg['mean'],std = cfg['std'])) 
        print(len(dataset))
    elif args.dataset == 'CRACK':
        if not os.path.exists(CRACK_ROOT):
            parser.error('Must specify dataset_root if specifying dataset')

        cfg = crack
        dataset = CRACKDetection(root=CRACK_ROOT,
                            transform=SSDAugmentation(cfg['min_dim'],
                            mean = cfg['mean'],std = cfg['std']))

    data_loader = data.DataLoader(dataset, args.batch_size,
                                  num_workers=args.num_workers,
                                  shuffle=True, collate_fn=detection_collate,
                                  pin_memory=True)

    valid_loader = data.DataLoader(valid_dataset, args.batch_size,
                                  num_workers=args.num_workers,
                                  shuffle=True, collate_fn=detection_collate,
                                  pin_memory=True)

    #build, load,  the net
    ssd_net = build_ssd('train',size = cfg['min_dim'],cfg = cfg)
    '''
    for name,param in ssd_net.named_parameters():
        if param.requires_grad:
            print(name)
    '''
    if args.resume:
        print('Resuming training, loading {}...'.format(args.resume))
        ssd_net.load_state_dict(torch.load(args.resume))

    if args.cuda:
        net = ssd_net.cuda()
    net.train()

    #optimizer
    optimizer = optim.SGD(net.parameters(), lr=args.lr, momentum=args.momentum,
                          weight_decay=args.weight_decay)


    #loss:SmoothL1\Iou\Giou\Diou\Ciou
    print(cfg['losstype'])
    criterion = MultiBoxLoss(cfg = cfg,overlap_thresh = 0.5,
                            prior_for_matching = True,bkg_label = 0,
                            neg_mining = True, neg_pos = 3,neg_overlap = 0.5,
                            encode_target = False, use_gpu = args.cuda,loss_name = cfg['losstype'])

    criterion_iou     = MultiBoxLoss(cfg = cfg,overlap_thresh = 0.5,
                            prior_for_matching = True,bkg_label = 0,
                            neg_mining = True, neg_pos = 3,neg_overlap = 0.5,
                            encode_target = False, use_gpu = args.cuda,loss_name = 'Iou')

    criterion_probiou = MultiBoxLoss(cfg = cfg,overlap_thresh = 0.5,
                            prior_for_matching = True,bkg_label = 0,
                            neg_mining = True, neg_pos = 3,neg_overlap = 0.5,
                            encode_target = False, use_gpu = args.cuda,loss_name = 'Piou')


    if args.visdom:
        import visdom
        viz = visdom.Visdom(env=cfg['work_name'])
        vis_title = 'SSD on ' + args.dataset
        vis_legend = ['Loc Loss', 'Conf Loss', 'Total Loss']
        iter_plot = create_vis_plot(viz,'Iteration', 'Loss', vis_title, vis_legend)
        epoch_plot = create_vis_plot(viz,'Epoch', 'Loss', vis_title+" epoch loss", vis_legend)
        #epoch_acc = create_acc_plot(viz,'Epoch', 'acc', args.dataset+" Acc",["Acc"])





    epoch_size = len(dataset) // args.batch_size
    print('Training SSD on:', dataset.name,epoch_size)
    iteration = args.start_iter
    step_index = 0
    loc_loss = 0
    conf_loss = 0
    BEST_LOSS      =  10000
    BEST_IOU50     =  10000
    BEST_PROBIOU50 =  10000
    print(args.max_epoch)
    for epoch in range(args.max_epoch):
        for ii, batch_iterator in tqdm(enumerate(data_loader)):
            iteration += 1

            if iteration in cfg['lr_steps']:
                step_index += 1
                adjust_learning_rate(optimizer, args.gamma, step_index)

            # load train data
            images, targets = batch_iterator
            #print(images,targets)
            if args.cuda:
                images = images.cuda()
                targets = [ann.cuda() for ann in targets]
            else:
                images = images
                targets = [ann for ann in targets]
            t0 = time.time()
            out = net(images,'train')
            optimizer.zero_grad()
            loss_l, loss_c = criterion(out, targets)
            loss = weight * loss_l + loss_c
            loss.backward()
            nn.utils.clip_grad_value_(net.parameters(), clip_value=1.0)
            optimizer.step()
            t1 = time.time()
            loc_loss += loss_l.item()
            conf_loss += loss_c.item()
            #print(iteration)
            if iteration % 10 == 0:
                print('timer: %.4f sec.' % (t1 - t0))
                print('iter ' + repr(iteration) + ' || Loss: %.4f ||' % (loss_l.item()), end=' ')


            if args.visdom:
                if iteration>20 and  iteration% 10 == 0:
                    update_vis_plot(viz,iteration, loss_l.item(), loss_c.item(),
                                iter_plot, epoch_plot, 'append')

        loss      = []
        iou50     = []
        probiou50 = []
        for ii, batch_iterator in tqdm(enumerate(valid_loader)):
            images, targets = batch_iterator
            if args.cuda:
                images  = images.cuda()
                targets = [ann.cuda() for ann in targets]
            else:
                images  = images
                targets = [ann for ann in targets]
            #net.eval()
            out  = net(images,'train')
            loss_l, loss_c = criterion(out, targets)
            loss.append(weight*loss_l.item()+loss_c.item())
            loss_l, loss_c = criterion_iou(out,targets)
            iou50.append(loss_l.item())
            loss_l, loss_c = criterion_probiou(out,targets)
            probiou50.append(loss_l.item())
            
        LOSS      = np.mean(np.array(loss))
        IOU50     = np.mean(np.array(iou50))
        PROBIOU50 = np.mean(np.array(probiou50))
        if LOSS < BEST_LOSS:
            model_L = net.state_dict()
            BEST_LOSS = LOSS
        if IOU50 < BEST_IOU50:
            model_I = net.state_dict()
            BEST_IOU50 = IOU50
        if PROBIOU50 < BEST_PROBIOU50:
            model_P = net.state_dict()
            BEST_PROBIOU50 = PROBIOU50
            #


        if epoch % 10 == 0 and epoch >60:#epoch>1000 and epoch % 50 == 0:
            print('Saving state, iter:', iteration)
            #print('loss_l:'+weight * loss_l+', loss_c:'+'loss_c')
            save_folder = args.work_dir+cfg['work_name']
            if not os.path.exists(save_folder):
                os.mkdir(save_folder)
            torch.save(net.state_dict(),args.work_dir+cfg['work_name']+'/ssd'+
                       repr(epoch)+'_.pth')
        if args.visdom:
            update_vis_plot(viz, epoch, loc_loss, conf_loss, epoch_plot, epoch_plot,
                                'append', epoch_size)
        loc_loss = 0
        conf_loss = 0

    torch.save(model_L, args.work_dir+cfg['work_name']+'/ssd'+'best_loss_.pth')
    torch.save(model_I, args.work_dir+cfg['work_name']+'/ssd'+'best_iou_.pth')
    torch.save(model_P, args.work_dir+cfg['work_name']+'/ssd'+'best_probiou_.pth')
    torch.save(net.state_dict(),args.work_dir+cfg['work_name']+'/ssd'+repr(epoch)+ str(args.weight) +'_.pth')

def adjust_learning_rate(optimizer, gamma, step):
    """Sets the learning rate to the initial LR decayed by 10 at every
        specified step
    # Adapted from PyTorch Imagenet example:
    # https://github.com/pytorch/examples/blob/master/imagenet/main.py
    """
    lr = args.lr * (gamma ** (step))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr
        print(param_group['lr'])


def create_vis_plot(viz,_xlabel, _ylabel, _title, _legend):
    return viz.line(
        X=torch.zeros((1,)).cpu(),
        Y=torch.zeros((1, 3)).cpu(),
        opts=dict(
            xlabel=_xlabel,
            ylabel=_ylabel,
            title=_title,
            legend=_legend
        )
    )

def create_acc_plot(viz,_xlabel, _ylabel, _title, _legend):
    return viz.line(
        X=torch.zeros((1,)).cpu(),
        Y=torch.zeros((1,)).cpu(),
        opts=dict(
            xlabel=_xlabel,
            ylabel=_ylabel,
            title=_title,
            legend=_legend
        )
    )


def update_vis_plot(viz,iteration, loc, conf, window1, window2, update_type,
                    epoch_size=1):
    viz.line(
        X=torch.ones((1, 3)).cpu() * iteration,
        Y=torch.Tensor([loc, conf, loc + conf]).unsqueeze(0).cpu() / epoch_size,
        win=window1,
        update=update_type
    )


def update_acc_plot(viz,iteration,acc, window1,update_type,
                    epoch_size=1):
    viz.line(
        X=torch.ones((1, 1)).cpu()*iteration,
        Y=torch.Tensor([acc]).unsqueeze(0).cpu(),
        win=window1,
        update=update_type
    )
    # initialize epoch plot on first iteration
    '''
    if iteration == 0:
        print(loc, conf, loc + conf)
        viz.line(
            X=torch.zeros((1, 3)).cpu(),
            Y=torch.Tensor([loc, conf, loc + conf]).unsqueeze(0).cpu(),
            win=window2,
            update=True
        )
    '''
if __name__ == '__main__':
    train()
