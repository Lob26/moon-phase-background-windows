---
id: TASK-5
title: Soportar o detectar el modo Span del fondo de pantalla
status: To Do
assignee: []
created_date: '2026-08-03 21:17'
labels:
  - rendering
dependencies: []
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
En modo Span (DESKTOP_WALLPAPER_POSITION = 5) Windows estira una sola imagen sobre todo el escritorio virtual, asi que SetWallpaper por monitor no significa nada. Hay que leer GetPosition (slot 11) al sondear y caer al camino de una sola imagen si es Span. Lo ideal seria ademas renderizar una imagen del ancho del escritorio virtual.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 En modo Span se usa el camino de una sola imagen y queda registrado el motivo
<!-- AC:END -->
