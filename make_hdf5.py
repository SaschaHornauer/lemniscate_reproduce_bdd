import numpy as np
import h5py

import torch
import models
import os
from Dataset_Stereo import Dataset
from torch.autograd.variable import Variable
import numpy as np

from util_moduls.Utils import get_device

from lib.NCEAverage import NCEAverage
from lib.NCECriterion import NCECriterion

import matplotlib.pyplot as plt

from test import NN, kNN

from scipy import misc

import pickle

'''
import subprocess

subprocess.call(["ulimit -n 64000"])
'''

def resize2d(img, size):
    return (torch.nn.functional.adaptive_avg_pool2d(Variable(img,requires_grad=False), size)).data


low_dim = 128
checkpoint = torch.load('model_best.pth.tar') #torch.load('checkpoint.pth.tar')
model = models.__dict__[checkpoint['arch']](low_dim=low_dim)
model = model.cuda()

state_dict = checkpoint['state_dict']

from collections import OrderedDict

print('epoch: {}'.format(checkpoint['epoch']))

lemniscate = checkpoint['lemniscate']

new_state_dict = OrderedDict()
for k, v in state_dict.items():
    name = k[7:] # remove `module.`
    new_state_dict[name] = v

# load params
model.load_state_dict(new_state_dict)

traindir = os.path.join('/data/carla_training_data/', 'train')
n_frames = 6
gpu = 0
j = 0
seed = 232323
batch_size = 8

train_dataset = Dataset(traindir, n_frames, 1, gpu)
train_sampler = None

train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size, 
                                           shuffle=(train_sampler is None), num_workers=j, 
                                           sampler=train_sampler)

torch.manual_seed(seed)
valdir = os.path.join('/data/carla_training_data/', 'val')
val_dataset = Dataset(valdir, n_frames, 1, gpu)
val_loader = torch.utils.data.DataLoader(val_dataset, batch_size=batch_size, 
                                         shuffle=True, num_workers=j)

ndata = train_dataset.__len__()
nce_k = 4096
nce_t = .07
nce_m = .5
iter_size = 1


#lemniscate = NCEAverage(gpu, low_dim, ndata, nce_k, nce_t, nce_m).to(get_device(gpu))
criterion = NCECriterion(ndata).to(get_device(gpu))

iter_size = 1

#hf = h5py.File('data_one.h5', 'w')
#with h5py.File('data.h5', "a") as f:
#    dset = f.create_dataset('img_names', (batch_size,), maxshape=(None,),
#                            dtype='S', chunks=(batch_size,))

print('create h5py data')
    
all_img_names = []
#all_imgs = []
all_id_nums = []
all_steer_truths = []
all_steer_preds = []
all_losses = []
all_steer_diffs = []

trainFeatures = lemniscate.memory.t()
trainLabels = torch.LongTensor(train_loader.dataset.train_labels).cuda()

'''
batch_img_names shape: (8, 5)
batch_imgs shape: (8, 5, 36, 94, 168)
batch_id_nums shape: (8, 5)
batch_steer_truths shape: (8, 6)
batch_steer_preds shape: (8, 5, 6)
loss shape: torch.Size([1])
batch_steer_diffs shape: (8, 5, 6)
'''

'''
all_img_names_dset = hf.create_dataset('all_img_names', (0,5), maxshape=(None,None), dtype='float')
#all_imgs_dset = hf.create_dataset('all_imgs', (0,5,36,94,168), maxshape=(None,None,None,None,None), dtype='float')
all_id_nums_dset = hf.create_dataset('all_id_nums', (0,5), maxshape=(None,None), dtype='float')
all_steer_truths_dset = hf.create_dataset('all_steer_truths', (0,6), maxshape=(None,None), dtype='float')
all_steer_preds_dset = hf.create_dataset('all_steer_preds', (0,5,6), maxshape=(None,None,None), dtype='float')
all_losses_dset = hf.create_dataset('all_losses', (0,), maxshape=(None,), dtype='float')
all_steer_diffs_dset = hf.create_dataset('all_steer_diffs', (0,5,6), maxshape=(None,None,None), dtype='float')
'''

for i, (input_imgs, input_steerings, indices) in enumerate(val_loader):

    #print("input_imgs shape: {}".format(input_imgs.shape))
    #print("input_steerings shape: {}".format(input_steerings.shape))

    og_input_imgs = input_imgs.clone().cpu().numpy()
    og_input_steerings = input_steerings.clone().cpu().numpy()

    input_imgs = input_imgs[:,12:18,:,:] #extract only img 3 out of 6
    input_steerings = input_steerings[:,0:3] #extract steers first 3 out of 6

    indices = indices.to(get_device(gpu))

    # Change the image size so it fits to the network
    input_imgs = resize2d(input_imgs, (224,224))
    

    '''
    input_imgs = np.array(input_imgs)

    f, axes = plt.subplots(2, input_imgs.shape[0])
    f.set_size_inches(30, 7)
    for k in range(input_imgs.shape[0]):
    #print(input_imgs.shape)
        for j in range(input_imgs.shape[1]/3):
            axes[j, k].imshow(input_imgs[k,3*j:3*j+3,:,:].transpose((1,2,0)))

    plt.show()
    '''

    #print('input_imgs: {}, input_steer: {}'.format(input_imgs.shape, input_steerings.shape))

    #feature = model(input_imgs, input_steerings)

    input_steerings = input_steerings.cuda(async=True)
    indices = indices.cuda(async=True)
    batchSize = input_imgs.size(0)

    #input_imgs = resize2d(input_imgs, (224,224))

    features = model(input_imgs, input_steerings)
    output = lemniscate(features, indices)
    loss = criterion(output, indices) / iter_size
    
    #net_time.update(time.time() - end)
    #end = time.time()

    dist = torch.mm(features, trainFeatures)

    yd, yi = dist.topk(5, dim=1, largest=True, sorted=True)
    candidates = trainLabels.view(1,-1).expand(batchSize, -1)
    retrieval = torch.gather(candidates, 1, yi)

    retrieval = retrieval.narrow(1, 0, 5).clone().cpu().numpy()#.view(-1)
    yd = yd.narrow(1, 0, 5)

    #print('retrieval shape: {}'.format(retrieval.shape))
    #print('retrieval numbers: {}'.format(retrieval))
    
    batch_img_names = []
    #batch_imgs = []
    batch_id_nums = []
    batch_steer_truths = []
    batch_steer_preds = []
    batch_steer_diffs = []

    image_steering_labels = []
    steer_diffs = []

    #print('input steerings shape: {}'.format(input_steerings.shape))
    

    for batch_id in range(len(input_imgs)):
        batch_i_steer = og_input_steerings[batch_id,:]
        #print('batch_i_steer shape: {}'.format(batch_i_steer.shape))

        ret_img_names = []
        #ret_imgs = []
        ret_id_nums = []
        ret_steer_preds = []
        ret_steer_diffs = []
        
        
        image_steering_label = []
        steer_diff = 0

        for top5_id in range(5):
            ret_ind = retrieval[batch_id, top5_id]
            img_steer_lab = train_loader.dataset[ret_ind][1].cpu().numpy()
            
            #print('ret_ind filename: {}'.format(train_loader.dataset.run_files[ret_ind].filename))
            ret_img_names.append(train_loader.dataset.run_files[ret_ind].filename)
            #ret_imgs.append(np.array(train_loader.dataset[ret_ind][0][:]))
            ret_id_nums.append(ret_ind)
            ret_steer_preds.append(img_steer_lab)
            ret_steer_diffs.append(np.abs((img_steer_lab - batch_i_steer)/2.))
            
        batch_img_names.append(ret_img_names)
        #batch_imgs.append(ret_imgs)
        batch_id_nums.append(ret_id_nums)
        batch_steer_truths.append(batch_i_steer)
        batch_steer_preds.append(ret_steer_preds)
        batch_steer_diffs.append(ret_steer_diffs)

    batch_img_names = np.array(batch_img_names)
    #batch_imgs = np.array(batch_imgs)
    batch_id_nums = np.array(batch_id_nums)
    batch_steer_truths = np.array(batch_steer_truths)
    batch_steer_preds = np.array(batch_steer_preds)
    batch_losses = np.array(loss.cpu().data)
    batch_steer_diffs = np.array(batch_steer_diffs)

    '''
    print('batch_img_names shape: {}'.format(batch_img_names.shape))
    print('batch_imgs shape: {}'.format(batch_imgs.shape))
    print('batch_id_nums shape: {}'.format(batch_id_nums.shape))
    print('batch_steer_truths shape: {}'.format(batch_steer_truths.shape))
    print('batch_steer_preds shape: {}'.format(batch_steer_preds.shape))
    print('loss shape: {}'.format(loss.shape))
    print('batch_steer_diffs shape: {}'.format(batch_steer_diffs.shape))
    '''
    '''
    batch_img_names shape: (8, 5)
    batch_imgs shape: (8, 5, 36, 94, 168)
    batch_id_nums shape: (8, 5)
    batch_steer_truths shape: (8, 6)
    batch_steer_preds shape: (8, 5, 6)
    loss shape: torch.Size([1])
    batch_steer_diffs shape: (8, 5, 6)
    '''

    '''
    dsets = [all_img_names_dset, 
             #all_imgs_dset, 
             all_id_nums_dset, 
             all_steer_truths_dset, 
             all_steer_preds_dset, 
             all_steer_diffs_dset]
    
    datas = [batch_img_names, 
             #batch_imgs, 
             batch_id_nums, 
             batch_steer_truths, 
             batch_steer_preds, 
             batch_steer_diffs]
    
    for dset_ind, dset in enumerate(dsets):
        dset.resize(dset.shape[0]+batch_size, axis=0)
        dset[-batch_size,:] = datas[dset_ind]
    
    
    all_losses_dset.resize(all_losses_dset.shape[0]+1, axis=0)
    all_losses_dset[-1] = batch_losses
    '''
    
    
    all_img_names.append(batch_img_names)
    #all_imgs.append(batch_imgs)
    all_id_nums.append(batch_id_nums)
    all_steer_truths.append(batch_steer_truths)
    all_steer_preds.append(batch_steer_preds)
    all_losses.append(batch_losses)
    all_steer_diffs.append(batch_steer_diffs)
    
    print('saved batch: {}'.format(i))
    
    
    
    '''
    if i > 1:
        break
    '''


all_img_names = np.array(all_img_names)
#all_imgs = np.array(all_imgs)
all_id_nums = np.array(all_id_nums)
all_steer_truths = np.array(all_steer_truths)
all_steer_preds = np.array(all_steer_preds)
all_losses = np.array(all_losses)
all_steer_diffs = np.array(all_steer_diffs)


'''
hf.create_dataset('all_img_names', data=all_img_names)
#hf.create_dataset('all_imgs', data=all_imgs)
hf.create_dataset('all_id_nums', data=all_id_nums)
hf.create_dataset('all_steer_truths', data=all_steer_truths)
hf.create_dataset('all_steer_preds', data=all_steer_preds)
hf.create_dataset('all_losses', data=all_losses)
hf.create_dataset('all_steer_diffs', data=all_steer_diffs)


hf.close()
'''

a = {'all_img_names': all_img_names, 
     'all_id_nums': all_id_nums,
     'all_steer_truths': all_steer_truths, 
     'all_steer_preds': all_steer_preds, 
     'all_losses': all_losses,
     'all_steer_diffs': all_steer_diffs}

with open('data.pickle', 'wb') as handle:
    pickle.dump(a, handle, protocol=pickle.HIGHEST_PROTOCOL)


