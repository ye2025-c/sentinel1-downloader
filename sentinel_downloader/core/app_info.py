#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application identity shared by the GUI and build script."""

APP_NAME = "Sentinel Downloader"
APP_VERSION = "4.6.0"


def display_name() -> str:
    return f"{APP_NAME} v{APP_VERSION}"
