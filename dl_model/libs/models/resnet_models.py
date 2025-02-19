from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import torch.nn as nn
import torch.utils.model_zoo as model_zoo


model_urls = {
  'resnet18': 'https://download.pytorch.org/models/resnet18-5c106cde.pth',
  'resnet34': 'https://download.pytorch.org/models/resnet34-333f7ec4.pth',
  'resnet50': 'https://download.pytorch.org/models/resnet50-19c8e357.pth',
  'resnet101': 'https://download.pytorch.org/models/resnet101-5d3b4d8f.pth',
  'resnet152': 'https://download.pytorch.org/models/resnet152-b121ed2d.pth',
}


def conv3x3(in_planes, out_planes, stride=1):
  """3x3 convolution with padding"""
  return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                   padding=1, bias=False)


def conv1x1(in_planes, out_planes, stride=1):
  """1x1 convolution"""
  return nn.Conv2d(in_planes, out_planes, kernel_size=1, stride=stride, bias=False)


class BasicBlock(nn.Module):
  expansion = 1

  def __init__(self, inplanes, planes, stride=1, downsample=None):
    super(BasicBlock, self).__init__()
    # Both self.conv1 and self.downsample layers downsample the input when stride != 1
    self.conv1 = conv3x3(inplanes, planes, stride)
    self.bn1 = nn.BatchNorm2d(planes)
    self.relu = nn.ReLU(inplace=True)
    self.conv2 = conv3x3(planes, planes)
    self.bn2 = nn.BatchNorm2d(planes)
    self.downsample = downsample
    self.stride = stride

  def forward(self, x):
    identity = x
    out = self.conv1(x)
    out = self.bn1(out)
    out = self.relu(out)

    out = self.conv2(out)
    out = self.bn2(out)
    if self.downsample is not None:
      identity = self.downsample(x)

    out += identity
    out = self.relu(out)
    return out


class Bottleneck(nn.Module):
  expansion = 4

  def __init__(self, inplanes, planes, stride=1, downsample=None):
    super(Bottleneck, self).__init__()
    # Both self.conv2 and self.downsample layers downsample the input when stride != 1
    self.conv1 = conv1x1(inplanes, planes)
    self.bn1 = nn.BatchNorm2d(planes)
    self.conv2 = conv3x3(planes, planes, stride)
    self.bn2 = nn.BatchNorm2d(planes)
    self.conv3 = conv1x1(planes, planes * self.expansion)
    self.bn3 = nn.BatchNorm2d(planes * self.expansion)
    self.relu = nn.ReLU(inplace=True)
    self.downsample = downsample
    self.stride = stride

  def forward(self, x):
    identity = x
    out = self.conv1(x)
    out = self.bn1(out)
    out = self.relu(out)

    out = self.conv2(out)
    out = self.bn2(out)
    out = self.relu(out)
    out = self.conv3(out)
    out = self.bn3(out)

    if self.downsample is not None:
      identity = self.downsample(x)
    out += identity
    out = self.relu(out)
    return out


class ResNet(nn.Module):
  def __init__(self, block, layers, input_channels,
               zero_init_residual=False,
               frozen_stages=[],
               version="imagenet"):
    super(ResNet, self).__init__()
    assert version in ["imagenet", "cifar"]
    self.version = version
    self.inplanes = 64
    self.frozen_stages = frozen_stages
    self.zero_init_residual = zero_init_residual

    # ops in the network
    self.conv1 = nn.Conv2d(input_channels, 64, kernel_size=7, stride=2, padding=3, bias=False)
    self.bn1 = nn.BatchNorm2d(64)
    self.relu = nn.ReLU(inplace=True)
    self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)


    # residual blocks
    self.layer1 = self._make_layer(block, 64, layers[0], stride=1)
    self.layer2 = self._make_layer(block, 128, layers[1], stride=2)
    self.layer3 = self._make_layer(block, 256, layers[2], stride=2)
    self.layer4 = self._make_layer(block, 512, layers[3], stride=2)

    # init params
    self.reset_params()

    # freeze part of the network
    self._freeze_stages()

  def reset_params(self):
    # init all params (you need to do this for pytorch < 1.2)
    for m in self.modules():
      if isinstance(m, nn.Conv2d):
        nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
      elif isinstance(m, nn.BatchNorm2d):
        nn.init.constant_(m.weight, 1.0)
        nn.init.constant_(m.bias, 0.0)

    # Zero-initialize the last BN in each residual branch,
    # so that the residual branch starts with zeros,
    # and each residual block behaves like an identity.
    # This improves the model by 0.2~0.3%
    # according to https://arxiv.org/abs/1706.02677
    if self.zero_init_residual:
      for m in self.modules():
        if isinstance(m, Bottleneck):
          nn.init.constant_(m.bn3.weight, 0.0)
        elif isinstance(m, BasicBlock):
          nn.init.constant_(m.bn2.weight, 0.0)

  def _make_layer(self, block, planes, blocks, stride=1):
    downsample = None
    if stride != 1 or self.inplanes != planes * block.expansion:
      downsample = nn.Sequential(
        conv1x1(self.inplanes, planes * block.expansion, stride),
        nn.BatchNorm2d(planes * block.expansion),
      )
    layers = []
    layers.append(block(self.inplanes, planes, stride, downsample))
    self.inplanes = planes * block.expansion
    for _ in range(1, blocks):
      layers.append(block(self.inplanes, planes))

    return nn.Sequential(*layers)

  def forward(self, x):
    x = self.conv1(x)
    x = self.bn1(x)
    x = self.relu(x)
    #x = self.maxpool(x)  # remove the pooling layer in observance of low resolution
    # residual blocks
    x1 = self.layer1(x)
    x2 = self.layer2(x1)
    x3 = self.layer3(x2)
    x4 = self.layer4(x3)
    # return the full feature pyramid
    return (x1, x2, x3, x4)

  def _freeze_stages(self):
    # train the full network with frozen_stages < 0
    if len(self.frozen_stages) == 0:
      return
    # stages from [0, 4] - the five conv blocks
    stage_mapping = [
      [self.conv1, self.bn1],
      [self.layer1],
      [self.layer2],
      [self.layer3],
      [self.layer4]
    ]
    # freeze the params (but still allow bn to aggregate the stats)
    for idx in self.frozen_stages:
      for m in stage_mapping[idx]:
        for param in m.parameters():
          if param.requires_grad:
            param.requires_grad = False

  def train(self, mode=True):
    super(ResNet, self).train(mode)
    self._freeze_stages()


def load_pretrained_model(model, model_id):
  "Make the loading verbose"
  # quick sanity check
  if model.version == "cifar":
    print("Pretrained models for CIFAR are not supported")
    return

  # load the model from model zoo and print the missing/unexpected keys
  missing_keys, unexpected_keys = model.load_state_dict(
    model_zoo.load_url(model_urls[model_id]), strict=False)
  if missing_keys:
    print("Missing keys:")
    for key in missing_keys:
      print(key)
  if unexpected_keys:
    print("Unexpected keys:")
    for key in unexpected_keys:
      print(key)


def resnet18(pretrained=False, **kwargs):
  """Constructs a ResNet-18 model.

  Args:
      pretrained (bool): If True, returns a model pre-trained on ImageNet
  """
  model = ResNet(BasicBlock, [2, 2, 2, 2], **kwargs)
  if pretrained:
    load_pretrained_model(model, 'resnet18')
  return model


def resnet34(pretrained=False, **kwargs):
  """Constructs a ResNet-34 model.

  Args:
      pretrained (bool): If True, returns a model pre-trained on ImageNet
  """
  model = ResNet(BasicBlock, [3, 4, 6, 3], **kwargs)
  if pretrained:
    load_pretrained_model(model, 'resnet34')
  return model


def resnet50(pretrained=False, **kwargs):
  """Constructs a ResNet-50 model.

  Args:
      pretrained (bool): If True, returns a model pre-trained on ImageNet
  """
  model = ResNet(Bottleneck, [3, 4, 6, 3], **kwargs)
  if pretrained:
    load_pretrained_model(model, 'resnet50')
  return model


def resnet101(pretrained=False, **kwargs):
  """Constructs a ResNet-101 model.

  Args:
      pretrained (bool): If True, returns a model pre-trained on ImageNet
  """
  model = ResNet(Bottleneck, [3, 4, 23, 3], **kwargs)
  if pretrained:
    load_pretrained_model(model, 'resnet101')
  return model


def resnet152(pretrained=False, **kwargs):
  """Constructs a ResNet-152 model.

  Args:
      pretrained (bool): If True, returns a model pre-trained on ImageNet
  """
  model = ResNet(Bottleneck, [3, 8, 36, 3], **kwargs)
  if pretrained:
    load_pretrained_model(model, 'resnet152')
  return model
