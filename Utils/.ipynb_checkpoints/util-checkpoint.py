import numpy as np
import string,random,os,shutil,torch,time,yaml,pickle,copy,math

from skimage.transform import resize
from skimage.morphology import disk
from skimage.filters import rank
import PIL.Image as Image

import os.path as osp


debug_mode = False


def save_checkpoint(args, state, is_best, filename='checkpoint.pth.tar'):
    savedir = os.path.join(args.snapshot_dir, args.arch, 'group_%d_of_%d'%(args.group, args.num_folds))
    if not os.path.exists(savedir):
        os.makedirs(savedir)

    savepath = os.path.join(savedir, filename)
    torch.save(state, savepath)
    if is_best:
        shutil.copyfile(savepath, os.path.join(args.snapshot_dir, 'group_%d_of_%d'%(args.group, args.num_folds)+'model_best.pth.tar'))

def get_save_dir(args):
    snapshot_dir = os.path.join(args.snapshot_dir, args.arch, 'group_%d_of_%d'%(args.group, args.num_folds))
    return snapshot_dir

def cprint(string, style = None):
    if not debug_mode and style != bcolors.FAIL and style != bcolors.OKBLUE:
        return
    if style is None:
        print(str(string))
    else:
        print(style + str(string) + bcolors.ENDC)

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def read_img(img_path):
    cprint('Reading Image ' + img_path, bcolors.OKGREEN)
    uint_image = np.array(Image.open(img_path))
    if len(uint_image.shape) == 2:
        tmp_image = np.zeros(uint_image.shape + (3,), dtype=np.uint8)
        tmp_image[:,:,0] = tmp_image[:,:,1] = tmp_image[:,:,2] = uint_image
        uint_image = tmp_image
    return np.array(uint_image, dtype=np.float32)/255.0

def read_mask(mask_path):
    #read mask
    m_uint = np.array(Image.open(mask_path))
    fg = np.unique(m_uint)
    if not (len(m_uint.shape) == 2 and ((len(fg) == 2 and fg[0] == 0 and fg[1] == 255) or (len(fg) == 1 and (fg[0] == 0 or fg[0] == 255)))):
        print(mask_path, fg, m_uint.shape)
        raise Exception('Error in reading mask')
    return np.array(m_uint, dtype=np.float32) / 255.0
    
    
def read_flo_file(file_path):
    """
    reads a flo file, it is for little endian architectures,
    first slice, i.e. data2D[:,:,0], is horizontal displacements
    second slice, i.e. data2D[:,:,1], is vertical displacements

    """
    with open(file_path, 'rb') as f:
        magic = np.fromfile(f, np.float32, count=1)
        if 202021.25 != magic[0]:
            cprint('Magic number incorrect. Invalid .flo file: %s' % file_path, bcolors.FAIL)
            raise  Exception('Magic incorrect: %s !' % file_path)
        else:
            w = np.fromfile(f, np.int32, count=1)
            h = np.fromfile(f, np.int32, count=1)
            data = np.fromfile(f, np.float32, count=2*w*h)
            data2D = np.reshape(data, (h[0], w[0], 2), order='C')
            return data2D


def write_flo_file(file_path, data2D):
    """
    writes a flo file, it is for little endian architectures,
    first slice, i.e. data2D[:,:,0], is horizontal displacements
    second slice, i.e. data2D[:,:,1], is vertical displacements

    """
    with open(file_path, 'wb') as f:
        magic = np.array(202021.25, dtype='float32')
        magic.tofile(f)
        h = np.array(data2D.shape[0], dtype='int32')
        w = np.array(data2D.shape[1], dtype='int32')
        w.tofile(f)
        h.tofile(f)
        data2D.astype('float32').tofile(f);
        
def add_noise_to_mask(cmask, r_param = (15, 15), mult_param = (20, 5), threshold = .2):
    radius = max(np.random.normal(*r_param), 1)
    mult = max(np.random.normal(*mult_param), 2)
    
    selem = disk(radius)
    mask2d = np.zeros(cmask.shape + (2,))
    mask2d[:, :, 0] = rank.mean((1 - cmask).copy(), selem=selem) / 255.0
    mask2d[:, :, 1] = rank.mean(cmask.copy(), selem=selem) / 255.0

    exp_fmask = np.exp(mult * mask2d);
    max_fmask = exp_fmask[:,:,1] / np.sum(exp_fmask, 2);
    max_fmask[max_fmask < threshold] = 0;
    
    return max_fmask
    
class Timer(object):
    def __init__(self):
        self.total_time = 0.
        self.calls = 0
        self.start_time = 0.
        self.diff = 0.
        self.average_time = 0.

    def tic(self):
        self.start_time = time.time()

    def toc(self, average=True):
        self.diff = time.time() - self.start_time
        self.total_time += self.diff
        self.calls += 1
        self.average_time = self.total_time / self.calls
        if average:
            return self.average_time
        else:
            return self.diff

def parse_file(input_path, output_path, dictionary):
    with open(input_path, 'r') as in_file:
        with open(output_path, 'w') as out_file:
            data = string.Template(in_file.read())
            out_file.write(data.substitute(**dictionary))
            

def crop(img, bbox, output_shape = None, resize_order = 1, clip = True):
    bsize = bbox.size()
    if bsize[0] == 0:
        raise Exception('Cropping bbox can not be empty.')
    
    img_bbox = BBox(0, img.shape[0], 0, img.shape[1])
    intbox = img_bbox.copy()
    intbox.intersect(bbox)
    
    output = np.zeros(bsize + img.shape[2:])
    output[(intbox.top-bbox.top):(intbox.bottom-bbox.top), (intbox.top-bbox.left):(intbox.bottom-bbox.left)] = img[intbox.top:intbox.bottom, intbox.left:intbox.right]
    
    if output_shape is None or tuple(output_shape) == intbox.size():
        return output
    return resize(output, output_shape, order = resize_order, mode = 'nearest', clip = clip, preserve_range=True)
        

def crop_undo(cropped_img, cropping_bbox, img_shape, resize_order = 1):
    bsize = cropping_bbox.size()
    if bsize != cropped_img.shape[:2]:
        cropped_img = resize(cropped_img, bsize, order = resize_order, mode = 'nearest', preserve_range=True)
    img = np.zeros(img_shape + cropped_img.shape[2:])    
    img_bbox = BBox(0, img.shape[0], 0, img.shape[1])
    intbox = img_bbox.copy()
    intbox.intersect(cropping_bbox)
    
    img[intbox.top:intbox.bottom, intbox.left:intbox.right] = cropped_img[(intbox.top-cropping_bbox.top):(intbox.bottom-cropping_bbox.top), (intbox.top-cropping_bbox.left):(intbox.bottom-cropping_bbox.left)]
    return img

def change_coordinates(array, down_scale, offset, order = 0, preserve_range = True):
    ##in caffe we have label_cordinate = down_scale * 'name'_coordinate + offset
    ##in python resize we have label_coordinate = down_scale * 'name'_coordinate + (down_scale - 1)/2 - pad
    ## ==> (down_scale - 1)/2 - pad = offset ==> pad = -offset + (down_scale - 1)/2
    pad = int(-offset + (down_scale - 1)/2)
    orig_h = array.shape[0]
    orig_w = array.shape[1]
    new_h = int(np.ceil(float(orig_h + 2 * pad) / down_scale))
    new_w = int(np.ceil(float(orig_w + 2 * pad) / down_scale))
    #floor or ceil?
    if pad > 0:
        pad_array = ((0,0),) * (len(array.shape) - 2) + ((pad, int(new_h * down_scale - orig_h - pad)), (pad, int(new_w * down_scale - orig_w - pad)))
        new_array = np.pad(array, pad_array, 'constant')
    elif pad == 0:
        new_array = array
    else:
        raise Exception
        
    if new_h != orig_h or new_w != orig_w:
        return resize(new_array, (new_h,new_w) + array.shape[2:], order = order, preserve_range = preserve_range)
    else:
        return new_array.copy()
        
#defaults is a list of (key, val) is val is None key is required field


def load_netflow_db(annotations_file, split, shuffle = False):
    if split == 'training':
        split = 1
    if split == 'test':
        split = 2
    annotations = np.loadtxt(annotations_file)
    frame_indices = np.arange(len(annotations))
    frame_indices = frame_indices[ annotations == split ]
    length = len(frame_indices)
    data_dir = osp.join(osp.dirname(osp.abspath(annotations_file)), 'data/')
    if shuffle:
        random.shuffle( frame_indices)

    return dict(frame_indices=frame_indices, data_dir=data_dir, length=length)





def compute_flow(T1, T2, object_size, img_size, flow = None):
    assert len(img_size) == 2 and len(object_size) == 2
    #final_flow(T1(i,j)) = T2( (i,j) + f1(i,j) ) - T1(i,j)
    # = (T2(i,j) + T2(f1(i,j)) - T2((0,0))) - T1(i, j)
    # = T2(i,j) - T1(i,j) + T2(f1(i,j)) - T2((0,0))
    # = A + B - T2((0,0)) where A = T2(i,j) - T1(i,j), B = T2(f1(i,j))
    # A(T1(i, j)) = T2(i,j) - T1(i,j) ==> A((m,n)) = T2(T1^-1(m,n)) - (m, n)
    # B(T1(i, j)) = T2(f1(i,j)) ==(see *)==> BT1(m,n) = B(T^-1(m,n))
        
    # * Given an image I and transformation T: (IT is the image after applying transformation T)
    # IT[k,l] = I[T^-1(k,l)]
        
    # 1) Compute A
    newx = np.arange(img_size[1])
    newy = np.arange(img_size[0])
    mesh_grid = np.stack(np.meshgrid(newx, newy), axis = 0)
    locs1 = np.array(mesh_grid, dtype='float')
    x,y = T1.itransform_points(locs1[0].ravel(), locs1[1].ravel(), object_size)
    x,y = T2.transform_points(x, y, object_size)
    locs2 = np.concatenate((x,y)).reshape((2,) + locs1[0].shape)
    final_flow = locs2 - locs1
        
    # 2) Compute B - T2((0,0))
    if flow is not None:
        # B
        x,y = T2.transform_points(flow[:,:,0].ravel(), flow[:,:,1].ravel(), object_size)
        b_flow = np.concatenate((x,y)).reshape((2,) + img_size)
        T1_cp = copy.deepcopy(T1)
        T1_cp.color_adjustment_param = None
        b_flow[0] = T1_cp.transform_img(b_flow[0], object_size, b_flow[0].shape, cval=0)
        b_flow[1] = T1_cp.transform_img(b_flow[1], object_size, b_flow[1].shape, cval=0)
        #T2((0,0))
        x0, y0 = T2.transform_points(np.array((0,)), np.array((0,)), object_size)
        b_flow[0] -= x0[0]
        b_flow[1] -= y0[0]
        
        #Add it to the final flow
        final_flow += b_flow
    return final_flow.transpose((1,2,0))
        
def sample_trans(base_tran, trans_dist):
    if base_tran is None and trans_dist is None:
        return None
    if base_tran is None:
        return trans_dist.sample()
    if trans_dist is None:
        return base_tran
    return base_tran + trans_dist.sample()


#################################### Util classes
#Integer value bbox 
#bottom and right are exlusive
class BBox:
    def __init__(self, top, bottom, left, right):
        self.init(top, bottom, left, right)
           
    def init(self, top, bottom, left, right):
        self.top = top
        self.bottom = bottom
        self.left = left
        self.right = right
        
    def intersect(self, bbox):
        if self.isempty() or bbox.isempty():
            self.init(0,0,0,0)
            return
        self.top = max(self.top, bbox.top)
        self.bottom = min(self.bottom, bbox.bottom)
        self.left = max(self.left, bbox.left)
        self.right = min(self.right, bbox.right)
   
    def pad(self, rpad, cpad=None):
        if self.isempty():
            raise Exception('Can not pad empty bbox')
        if cpad is None:
            cpad = rpad
        self.top -= rpad
        self.bottom += rpad
        self.left -= cpad
        self.right += cpad
       
    def scale(self, rscale, cscale=None):
        if self.isempty():
            return
        if cscale is None:
            cscale = rscale
        rpad = int((rscale - 1) * (self.bottom - self.top) / 2.0)
        cpad = int((cscale - 1) * (self.right - self.left) / 2.0)
        self.pad(rpad, cpad)
    
    def move(self, rd, cd):
        self.top += rd
        self.bottom += rd
        self.left += cd
        self.right += cd
        
    def isempty(self):
        return (self.bottom <= self.top) or (self.right <= self.left)
    
    def size(self):
        if self.isempty():
            return (0,0)
        return (self.bottom - self.top, self.right - self.left)
        
    def copy(self):
        return copy.copy(self)
    @staticmethod
    def get_bbox(img):
        if img.sum() == 0:
            return BBox(0, 0, 0, 0)
        rows = np.any(img, axis=1)
        cols = np.any(img, axis=0)
        top, bottom = np.where(rows)[0][[0, -1]]
        left, right = np.where(cols)[0][[0, -1]]
        return BBox(top, bottom+1, left, right+1)
    
class Cache:
    def __init__(self, max_size = 10):
        self.max_size = max_size
        self.cache = dict()
        self.key_queue = []
    def has_key(self, key):
        return key in self.cache

    def __setitem__(self, key, value):
        if key in self.cache:
            self.__delitem__(key)
        self.cache.__setitem__(key, copy.deepcopy(value))
        self.key_queue.append(key)
        if len(self.cache) > self.max_size:
            self.__delitem__(self.key_queue[0])
        
    def __getitem__(self, key):
        #assert key in self.cache
        self.key_queue.remove(key)
        self.key_queue.append(key)
        return copy.deepcopy(self.cache.__getitem__(key))
        
    def __delitem__(self, key):
        self.cache.__delitem__(key)
        self.key_queue.remove(key)

class Map(dict):
    """
    Example:
    m = Map({'first_name': 'Eduardo'}, last_name='Pool', age=24, sports=['Soccer'])
    """
    def __init__(self, *args, **kwargs):
        super(Map, self).__init__(*args, **kwargs)
        for arg in args:
            if isinstance(arg, dict):
                for k, v in arg.items():
                    self[k] = v

        if kwargs:
            for k, v in kwargs.items():
                self[k] = v

    def __getattr__(self, attr):
        return self.get(attr)

    def __setattr__(self, key, value):
        self.__setitem__(key, value)

    def __setitem__(self, key, value):
        super(Map, self).__setitem__(key, value)
        self.__dict__.update({key: value})

    def __delattr__(self, item):
        self.__delitem__(item)

    def __delitem__(self, key):
        super(Map, self).__delitem__(key)
        del self.__dict__[key]
        
########################################################################### Sequence Generator ######################################################################## 
class VideoPlayer:
    def __init__(self, video_item, base_trans = None, frame_trans_dist = None, frame_noise_dist = None, step = 1, offset = 0, max_len = np.inf, flo_method = None):
        self.cache = Cache()
        self.name = video_item.name
        if offset != 0:
            self.name += '_o' + str(offset)
            
        if step != 1:
            self.name += '_s' + str(step)
            
        if not np.isinf(max_len):
            self.name += '_m' + str(max_len)
        
        self.video_item = video_item
        self.step = step
        self.offset = offset
        self.max_len = max_len
        self.flo_method = flo_method
        
        ##compute img_ids
        if step > 0:
            a = self.offset
            b = self.video_item.length
        elif step < 0:
            a = self.video_item.length - 1 - self.offset
            b = - 1    
        self.img_ids = range(a, b, self.step)
        if not np.isinf(self.max_len):
            self.img_ids = self.img_ids[:self.max_len]
        self.length = len(self.img_ids)
        #cprint(str(self.img_ids), bcolors.OKBLUE)
        ##compute mappings
        self.mappings = None
        self.gt_mappings = None
        if base_trans is not None or frame_trans_dist is not None:
            self.name += '_' + str(random.randint(0, 1e10))
            self.mappings = []
            self.gt_mappings = []
            for i in range(self.length):
                mapping = sample_trans(base_trans, frame_trans_dist)
                gt_mapping = sample_trans(mapping, frame_noise_dist)
                self.mappings.append(mapping)
                self.gt_mappings.append(gt_mapping)
    
    def get_frame(self, frame_id, compute_iflow = False):
        if self.cache.has_key(frame_id):
            img, mask, obj_size = self.cache[frame_id]
            assert(np.all(img >= 0) and np.all(img <= 1.0))
        else:
            img_id = self.img_ids[frame_id]
            # img = self.video_item.read_img(img_id)
            img, img_path = self.video_item.read_img(img_id)
            assert(np.all(img >= 0) and np.all(img <= 1.0))
            try:
                mask = self.video_item.read_mask(img_id)
                obj_size = np.array(BBox.get_bbox(mask).size())
            except IOError:
                cprint('Failed to load mask \'' + str(img_id) + '\' for video \'' + self.name + '\'. Return None mask..', bcolors.FAIL)
                mask = None
                obj_size = np.array([50, 50])
                
            if self.mappings is not None:
                img = self.mappings[frame_id].transform_img(img.copy(), obj_size, img.shape[:2], mask)
                if mask is not None:
                    mask  = self.mappings[frame_id].transform_mask(mask.copy(), obj_size, mask.shape)[0]
                    mask[mask == -1] = 0
            self.cache[frame_id] = (img, mask, obj_size)
        output = dict(image=img, mask=mask, image_path=img_path)
        
        if compute_iflow:
            try:
                iflow = self.video_item.read_iflow(img_id, self.step, self.flo_method)
            except Exception as e:
                cprint('Failed to load \'' + self.flo_method + '\' iflow for video ' + self.name + '. Return zero iflow..', bcolors.FAIL)
                iflow = np.zeros(img.shape[:2] + (2,))
            if self.mappings is None:
                output['iflow'] = iflow
            else:
                output['iflow'] = compute_flow(self.mappings[frame_id], self.gt_mappings[frame_id - 1], obj_size, img.shape[:2], flow = iflow)
        
        if 'mask' in output and output['mask'] is not None:
            assert output['mask'].shape[0] == output['image'].shape[0] and output['mask'].shape[1] == output['image'].shape[1]
        if 'iflow' in output:
            assert output['iflow'].shape[0] == output['image'].shape[0] and output['iflow'].shape[1] == output['image'].shape[1]
        return output

class ImagePlayer:
    def __init__(self, image_item, base_trans, frame_trans_dist, frame_noise_dist, compute_iflow = False, length = 2):
        self.name = image_item.name + '_' + str(random.randint(0, 1e10))
        self.length = length
        self.imgs = []
        self.masks = []
        self.image_item = image_item
        
        img = image_item.read_img()
        mask = image_item.read_mask()
        obj_size = BBox.get_bbox(mask).size()
        mappings = []
        gt_mappings = []
        for i in range(length):
            mapping = sample_trans(base_trans, frame_trans_dist)
            #debug
            #print '>'*10, 'Base Trans = ', base_trans
            #print '>'*10, 'Frame Trans = ', frame_trans_dist
            gt_mapping = sample_trans(mapping, frame_noise_dist)
            if gt_mapping is not None:
                timg = mapping.transform_img(img.copy(), obj_size, img.shape[:2], mask)
                tmask  = mapping.transform_mask(mask.copy(), obj_size, mask.shape)[0]
            else:
                timg = img.copy()
                tmask = mask.copy()
            tmask[tmask == -1] = 0          
            self.imgs.append(timg)
            self.masks.append(tmask)
            gt_mappings.append(gt_mapping)
            mappings.append(mapping)
            
        if compute_iflow:
            self.iflows = [None]
            for i in range(1, length):
                iflow = compute_flow(mappings[i], gt_mappings[i - 1], obj_size, mask.shape)
                self.iflows.append(iflow)

    def get_frame(self, frame_id, compute_iflow = False):
        output = dict(image=self.imgs[frame_id], mask=self.masks[frame_id])
        if compute_iflow:
            output['iflow'] = self.iflows[frame_id]
        return output 

