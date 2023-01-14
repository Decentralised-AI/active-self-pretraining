'''
Adapted from 

cite the pytorch impl of SimCLR

with little modifications
'''


import torchvision.transforms as transforms

class TransformsSimCLR():
    """
    A stochastic data augmentation module that transforms any given data example randomly
    resulting in two correlated views of the same example,
    denoted x ̃i and x ̃j, which we consider as a positive pair.
    """
    
    def __init__(self, size):
        s = 1

        color_jitter = transforms.ColorJitter(
            0.8 * s, 0.8 * s, 0.8 * s, 0.2 * s
        )
        self.train_transform = transforms.Compose(
            [
                transforms.RandomResizedCrop(size, scale=(0.2, 1.0)),
                transforms.RandomHorizontalFlip(),  # with 0.5 probability
                transforms.RandomApply([color_jitter], p=0.8),
                transforms.RandomGrayscale(p=0.2),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                     std=[0.229, 0.224, 0.225])
            ]
        )

        self.test_transform = transforms.Compose(
            [
                transforms.Resize((size, size)),
                transforms.ToTensor(),
            ]
        )

    def __call__(self, x, is_train=True):
        if not is_train:
            return self.test_transform(x)

        # return self.train_transform(x), self.train_transform(x)
        return self.train_transform(x)