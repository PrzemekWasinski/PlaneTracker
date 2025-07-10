def draw_text(window, text, font, text_col, x, y):
    img = font.render(text, True, text_col)
    window.blit(img, (x, y))

def draw_text_centered(window, text, font, rgb_val, x, y):
    img = font.render(text, True, rgb_val)
    rect = img.get_rect(center=(x, y))
    window.blit(img, rect)

def draw_fading_text(window, text, font, rgb_val, x, y, alpha):
    img = font.render(text, True, rgb_val)
    img.set_alpha(alpha)
    rect = img.get_rect(center=(x, y))
    window.blit(img, rect)