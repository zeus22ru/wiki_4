#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API маршруты для работы с документами
"""

from flask import Blueprint

# Создаем Blueprint для маршрутов документов
documents_bp = Blueprint('documents', __name__, url_prefix='/api/documents')

# TODO: Реализовать маршруты документов
# POST /api/documents/upload - загрузка документа
# GET /api/documents - список документов
# DELETE /api/documents/<id> - удаление документа
