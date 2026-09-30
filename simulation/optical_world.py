"""Opt-in synthetic lens response, not a validated real-space sensor model.

Classic World remains unmodified. This processing happens BEFORE detection,
so the preview shows the same pixels the model actually receives.
"""
import cv2
import numpy as np
import pygame
from simulation.world import World

class OpticalWorld(World):
    def render(self,*args,**kwargs):
        surface,occluded=super().render(*args,**kwargs)
        rgb=np.transpose(pygame.surfarray.array3d(surface),(1,0,2))
        # Small point-spread function and restrained optical scatter. Do not
        # introduce image-only beacon coordinates or alter ground truth.
        core=cv2.GaussianBlur(rgb,(5,5),.65).astype(np.float32)
        highlights=np.maximum(rgb.astype(np.float32)-110.,0.)
        halo=cv2.GaussianBlur(highlights,(19,19),3.)*.18
        output=np.clip(core+halo,0,255).astype(np.uint8)
        pygame.surfarray.blit_array(surface,np.transpose(output,(1,0,2)))
        return surface,occluded

def make_world(cfg):
    return OpticalWorld(cfg) if cfg.get('rendering',{}).get('profile')=='optical' else World(cfg)
