import os 

losses = ['Piou', 'SmoothL1', 'Ciou']#, 'Iou', 'Giou', 'Diou']
work_n = ['PIOU', 'SL1', 'CIOU']#,'IOU','GIOU','DIOU']

for i in range(len(losses)):
    os.system('python tools/train.py --loss '+losses[i]+' --work_name SSD300_VOC_FPN_'+work_n[i])
