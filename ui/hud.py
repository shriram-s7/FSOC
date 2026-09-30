"""
HUD overlay — drawn on top of the camera feed.
Stage 2: adds camera pan/tilt, uncertainty, occlusion status.
"""
import pygame

class HUD:
    def __init__(self, cfg):
        self.cfg = cfg
        pygame.font.init()
        self.font_large = pygame.font.SysFont('Consolas', 22, bold=True)
        self.font_small = pygame.font.SysFont('Consolas', 16)
        self.font_tiny  = pygame.font.SysFont('Consolas', 13)

    def render(self, surface, fps, sim_time, camera=None,
               target_az=None, target_el=None,
               uncertainty=None, occluded=False, extra_info=None):
        W, H = surface.get_size()

        # FPS
        fps_color = (0,255,80) if fps>=50 else (255,200,0) if fps>=30 else (255,60,60)
        surface.blit(self.font_large.render(f'FPS: {fps:.0f}', True, fps_color), (12,10))
        surface.blit(self.font_small.render(f'T: {sim_time:.1f}s', True, (160,200,255)), (12,38))

        # Title
        title = self.font_small.render('FSOC-PAT SIMULATOR  |  STAGE 6', True, (100,140,200))
        surface.blit(title, title.get_rect(centerx=W//2, top=10))

        # Camera state — top right
        if camera is not None:
            lines = [
                f'CAM PAN:  {camera.pan:+.2f}°',
                f'CAM TILT: {camera.tilt:+.2f}°',
            ]
            if target_az is not None:
                lines.append(f'TGT AZ:   {target_az:+.2f}°')
                lines.append(f'TGT EL:   {target_el:+.2f}°')
            if uncertainty is not None:
                lines.append(f'UNCERT:   ±{uncertainty:.2f}°')

            y = 10
            for line in lines:
                txt = self.font_tiny.render(line, True, (180, 220, 180))
                surface.blit(txt, (W - txt.get_width() - 12, y))
                y += 18

        # Occlusion badge
        if occluded:
            badge = self.font_small.render('⬛ OCCLUDED', True, (255, 80, 80))
            surface.blit(badge, badge.get_rect(centerx=W//2, top=36))

        # Extra info — bottom left
        if extra_info:
            y = H - 20 - len(extra_info) * 18
            for key, val in extra_info.items():
                txt = self.font_tiny.render(f'{key}: {val}', True, (140,180,140))
                surface.blit(txt, (12, y))
                y += 18

        # Controls hint
        hints = self.font_tiny.render(
            'ARROW KEYS: pan/tilt camera  |  ESC: quit', True, (70,70,100))
        surface.blit(hints, (W - hints.get_width() - 10, H - 20))
