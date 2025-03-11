import pygame
from pygame.locals import *
import os
import psutil
from time import gmtime, strftime
import random

pygame.init()

width = 800
height = 480

window = pygame.display.set_mode((width, height))
#icon = pygame.image.load(os.path.join("textures", "images", "_icon.png")) 
#pygame.display.set_icon(icon)
#pygame.display.set_caption("Fishing Game")

def draw_text(text, font, text_col, x, y):
    img = font.render(text, True, text_col)
    window.blit(img, (x, y))

text_font1 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 50)
text_font2 = pygame.font.Font(os.path.join("textures", "DS-DIGI.TTF"), 40)

messages = []

run = True
while run:
    pygame.draw.rect(window, (0, 0, 0), (0, 0, width, height))

    current_time = strftime("%H:%M:%S", gmtime())
    current_date = strftime("%d/%m/%Y", gmtime())
    ram_percentage = psutil.virtual_memory()[2]

    if len(messages) > 20:
        messages.pop()

    for event in pygame.event.get():    
        if event.type == pygame.QUIT:
            run = False

    #Time
    draw_text(str(current_time), text_font1, (255, 0, 0), 628, 10)
    draw_text(str(current_date), text_font2, (255, 0, 0), 620, 50)

    #Performance
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as temp:
        cpu_temp = int(temp.read()) / 1000 
    draw_text("RAM: " + str(ram_percentage) + "%", text_font2, (255, 255, 255), 626, 100)
    draw_text("CPU: " + str(int(cpu_temp)) + "*C", text_font2, (255, 255, 255), 626, 135)

    start = 10
    for i in range(0, len(messages)):
        draw_text(messages[i], text_font2, (255, 255, 255), 20, start)
        start += 40

    if random.randint(0, 60) < 2:
        message = random.randint(0, 10000)
        messages.insert(0, str(message))

    pygame.display.update()

pygame.quit()

