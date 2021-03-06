from torch import nn
from . import fc_resnet as fc_resnet
from . import context_pooling
import torch


class PSPNet(nn.Module):
    def __init__(self, num_class, base_model='resnet101', dropout=0.1, partial_bn=False, scale_series=[10, 20, 30, 60]):
        super(PSPNet, self).__init__()

        self.dropout = dropout
        self._enable_pbn = partial_bn
        self.num_class = num_class

        if partial_bn:
            self.partialBN(True)

        self._prepare_base_model(base_model)
        # self._prepare_aux_loss(num_class)
        self.context_model = context_pooling.PSPP(self.base_model.feature_dim, scale_series=scale_series)
        self.classifier = nn.Conv2d(self.context_model.feature_dim, num_class, kernel_size=1)

    def _prepare_base_model(self, base_model):
        if 'resnet' in base_model:
            self.base_model = getattr(fc_resnet, 'fc_' + base_model)(pretrained=True)
            self.input_mean = self.base_model.input_mean
            self.input_std = self.base_model.input_std
        else:
            raise ValueError('Unknown base model: {}'.format(base_model))

    def _prepare_aux_loss(self, num_class):
        layers = []
        shrink_dim = int(self.base_model.mid_feature_dim / 4)

        layers.append(nn.Conv2d(self.base_model.mid_feature_dim, shrink_dim, kernel_size=3, padding=1, bias=False))
        layers.append(nn.BatchNorm2d(shrink_dim))
        layers.append(nn.ReLU(inplace=True)) # inplace=True
        if self.dropout > 0:
            layers.append(nn.Dropout2d(p=self.dropout, inplace=True)) # True
        layers.append(nn.Conv2d(shrink_dim, num_class, kernel_size=1))
        self.aux_loss = nn.Sequential(*layers)

    def train(self, mode=True):
        """
        Override the default train() to freeze the BN parameters
        :return:
        """
        super(PSPNet, self).train(mode)
        if self._enable_pbn:
            print("Freezing BatchNorm2D.")
            for m in self.base_model.modules():
                if isinstance(m, nn.BatchNorm2d):
                    m.eval()
                    # shutdown update in frozen mode
                    m.weight.requires_grad = False
                    m.bias.requires_grad = False

    def partialBN(self, enable):
        self._enable_pbn = enable

    def get_optim_policies(self):
        base_weight = []
        base_bias = []
        base_bn = []

        addtional_weight = []
        addtional_bias = []
        addtional_bn = []

        for m in self.base_model.modules():
            if isinstance(m, nn.Conv2d):
                ps = list(m.parameters())
                base_weight.append(ps[0])
                if len(ps) == 2:
                    base_bias.append(ps[1])
            elif isinstance(m, nn.BatchNorm2d):
                base_bn.extend(list(m.parameters()))

        if self.context_model is not None:
            for m in self.context_model.modules():
                if isinstance(m, nn.Conv2d):
                    ps = list(m.parameters())
                    addtional_weight.append(ps[0])
                    if len(ps) == 2:
                        addtional_bias.append(ps[1])
                elif isinstance(m, nn.BatchNorm2d):
                    addtional_bn.extend(list(m.parameters()))

        if self.classifier is not None:
            for m in self.classifier.modules():
                if isinstance(m, nn.Conv2d):
                    ps = list(m.parameters())
                    addtional_weight.append(ps[0])
                    if len(ps) == 2:
                        addtional_bias.append(ps[1])
                elif isinstance(m, nn.BatchNorm2d):
                    addtional_bn.extend(list(m.parameters()))

        '''if self.aux_loss is not None:
            for m in self.aux_loss.modules():
                if isinstance(m, nn.Conv2d):
                    ps = list(m.parameters())
                    addtional_weight.append(ps[0])
                    if len(ps) == 2:
                        addtional_bias.append(ps[1])
                elif isinstance(m, nn.BatchNorm2d):
                    addtional_bn.extend(list(m.parameters()))'''

        return [
            {
                'params': addtional_weight,
                'lr_mult': 10,
                'decay_mult': 1,
                'name': "addtional weight"
            },
            {
                'params': addtional_bias,
                'lr_mult': 20,
                'decay_mult': 1,
                'name': "addtional bias"
            },
            {
                'params': addtional_bn,
                'lr_mult': 10,
                'decay_mult': 0,
                'name': "addtional BN scale/shift"
            },
            {
                'params': base_weight,
                'lr_mult': 1,
                'decay_mult': 1,
                'name': "base weight"
            },
            {
                'params': base_bias,
                'lr_mult': 2,
                'decay_mult': 0,
                'name': "base bias"
            },
            {
                'params': base_bn,
                'lr_mult': 1,
                'decay_mult': 0,
                'name': "base BN scale/shift"
            },
        ]

    def forward(self, x):
        input_size = tuple(x.size()[2:4])
        x = self.base_model(x)
        # mid_x = torch.sum(x, 1) # newly_added
        # mid_x = mid_x * mid_x
        # print(mid_x.shape)
        # mid_x = torch.nn.functional.softmax(mid_x.view(-1, 13568), 1)
        # x, mid_x = self.base_model(x, mid_feature=True)

        # mid_x = self.aux_loss(mid_x)
        # mid_x = nn.functional.upsample(mid_x, size=input_size, mode='bilinear')

        x = self.context_model(x)
        x = nn.functional.dropout2d(x, p=self.dropout, training=self.training, inplace=False) # True
        # mid_x = torch.sum(x, 1) # newly_added
        # mid_x = mid_x * mid_x
        # mid_x = x
        # print(mid_x.shape)
        x = self.classifier(x)
        x = nn.functional.upsample(x, size=input_size, mode='bilinear')

        return x #, mid_x #, mid_x # newly added
