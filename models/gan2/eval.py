import torch
from models.gan2.metrics import inception_score
from models.gan2.metrics.fid_score import calculate_fid_given_images
import numpy as np
from scipy.stats import truncnorm

class Evaluator(object):
    def __init__(self, generator, zdist, ydist, batch_size=64,
                 inception_nsamples=10000, device=None, fid_real_samples=None,
                 fid_sample_size=10000):
        self.generator = generator
        self.zdist = zdist
        self.ydist = ydist
        self.inception_nsamples = inception_nsamples
        self.batch_size = batch_size
        self.device = device

        if fid_real_samples is not None:
            self.fid_real_samples = fid_real_samples.numpy()
            self.fid_sample_size = fid_sample_size

    def compute_inception_score(self):
        self.generator.eval()
        imgs = []
        while(len(imgs) < self.inception_nsamples):
            ztest = self.zdist.sample((self.batch_size,))
            ytest = self.ydist.sample((self.batch_size,))

            samples, _ = self.generator(ztest, ytest)
            samples = [s.data.cpu().numpy() for s in samples]
            imgs.extend(samples)

        inception_imgs = imgs[:self.inception_nsamples]
        score, score_std = inception_score(
            inception_imgs, device=self.device, resize=True, splits=10,
        batch_size=self.batch_size)

        fid_imgs = np.array(imgs[:self.fid_sample_size])
        if self.fid_real_samples is not None:
            fid = calculate_fid_given_images(
                self.fid_real_samples,
                fid_imgs,
                batch_size=self.batch_size,
                cuda=True)

        return score, score_std, fid

    def create_samples(self, z, y=None):
        self.generator.eval()
        batch_size = z.size(0)
        # Parse y
        if y is None:
            y = self.ydist.sample((batch_size,))
        elif isinstance(y, int):
            y = torch.full((batch_size,), y,
                           device=self.device, dtype=torch.int64)
        # Sample x
        with torch.no_grad():
            x = self.generator(z, y)

        # device = next(self.generator.parameters()).device
        # dim_z = self.generator.embedding.weight.size(1)

        # tmp=0.3
        # num=200

        # embeddings = truncnorm(-tmp, tmp).rvs(num * dim_z).astype("float32").reshape(num, dim_z)
        # embeddings = torch.tensor(embeddings,device=device)

        # image_tensors = self.generator(embeddings, y)

        # return image_tensors

        return x
