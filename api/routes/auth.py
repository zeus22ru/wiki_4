#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API маршруты для аутентификации
"""

from flask import Blueprint

# Создаем Blueprint для маршрутов аутентификации
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# TODO: Реализовать маршруты аутентификации
# POST /api/auth/register - регистрация
# POST /api/auth/login - вход
# POST /api/auth/logout - выход
# GET /api/auth/me - текущий пользователь
