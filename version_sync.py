from __future__ import annotations
import os
import logging

log = logging.getLogger(__name__)
FALLBACK = '0.1.11'


def _plugin_root():
    return os.path.dirname(os.path.abspath(__file__))


def _yaml_path():
    return os.path.join(_plugin_root(), 'plugin.yaml')


def read_plugin_yaml_version():
    path = _yaml_path()
    try:
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        v = (data.get('version') or '').strip()
        return v or None
    except Exception as e:
        log.warning('[vibe_trading] read_plugin_yaml_version failed: %s', e)
        return None


def write_plugin_yaml_version(new_version):
    path = _yaml_path()
    try:
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return False
        if (data.get('version') or '').strip() == new_version:
            return True
        data['version'] = new_version
        with open(path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        return True
    except Exception as e:
        log.warning('[vibe_trading] could not update plugin.yaml: %s', e)
        return False


def _installed_package_version():
    try:
        import importlib.metadata as md
        return md.version('vibe-trading-ai')
    except Exception as e:
        log.warning('[vibe_trading] importlib.metadata failed: %s', e)
        return None


def sync_plugin_version():
    pkg_ver = _installed_package_version()
    if not pkg_ver:
        return None
    current = read_plugin_yaml_version()
    if current == pkg_ver:
        return None
    if write_plugin_yaml_version(pkg_ver):
        log.info('[vibe_trading] auto-synced plugin.yaml %s -> %s', current or '(unset)', pkg_ver)
        return pkg_ver
    return None
