'''
Vibe-Trading plugin — unit tests for plugin internals.

Runs OUTSIDE the A0 runtime with plain pytest (host venv):

    pytest usr/plugins/vibe_trading/tests/test_plugin_internals.py -q

Covers:
  - version lockstep: the five static sites + plugin.yaml must agree
  - scripts/check_v22_contract.py: green on the real tree, and catches
    version drift / disabled toggle on a synthetic tree
  - hooks._build_mcp_entry: plugin config → MCP server entry translation
    (MARKET_DATA_ORDER_* whitelist + normalization, qveris passthrough,
    data_cache, risk_tier, hard invariants disabled=false / init=30 /
    tool=300)
  - vibe_trading_cache: TTL semantics (expiry via the `now` param, the
    ttl_seconds alias, 'foo.*' wildcards, fresh() loader-once)
  - source-contract guards for api/shadow.py and api/portfolio.py, which
    import helpers.api (framework-only) and therefore cannot be imported
    here: assert the journal-hash cache key and the upstream-CLI fallback
    exist in source.

Single-quote string literals only (plugin-wide constraint) — test bodies
may use double quotes for strings that contain single quotes.
'''

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_ROOT / 'scripts'

_import_counter = [0]


def _import_module(name: str, path: Path):
    '''Import a file by path under an explicit module name.'''
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _unique_name(prefix: str) -> str:
    _import_counter[0] += 1
    return prefix + '_' + str(_import_counter[0])


@pytest.fixture(scope='module')
def checker():
    '''The real contract checker, rooted at the real plugin tree.'''
    return _import_module(_unique_name('vibe_check_v22'), SCRIPTS_DIR / 'check_v22_contract.py')


@pytest.fixture(scope='module')
def hooks_mod():
    '''hooks.py with the plugin's own version_sync pre-registered, so the
    module-level `from version_sync import ...` resolves to the plugin's
    copy rather than whatever a repo conftest may have left behind.'''
    _import_module('version_sync', PLUGIN_ROOT / 'version_sync.py')
    return _import_module('hooks', PLUGIN_ROOT / 'hooks.py')


@pytest.fixture(autouse=True)
def _clean_cache():
    '''Flush the shared TTL cache around every test.'''
    sys.path.insert(0, str(PLUGIN_ROOT))
    import vibe_trading_cache as vcache
    vcache.flush()
    yield
    vcache.flush()


# ---------------------------------------------------------------------------
# Version lockstep
# ---------------------------------------------------------------------------

def test_lockstep_manifest_equals_fallback_equals_expected():
    manifest = yaml.safe_load((PLUGIN_ROOT / 'plugin.yaml').read_text(encoding='utf-8'))
    manifest_version = str(manifest.get('version') or '').strip()
    vs = _import_module(_unique_name('vibe_vs'), PLUGIN_ROOT / 'version_sync.py')
    ex_src = (PLUGIN_ROOT / 'execute.py').read_text(encoding='utf-8')
    match = re.search(r"EXPECTED_VERSION\s*=\s*['\"]([^'\"]+)['\"]", ex_src)
    assert match, 'EXPECTED_VERSION not found in execute.py'
    assert vs.FALLBACK == manifest_version == match.group(1)


def test_lockstep_all_five_sites(checker):
    values = {}
    for label, rel, pattern in checker._LOCKSTEP_SITES:
        val, err = checker._read_version_at(str(PLUGIN_ROOT), rel, pattern)
        assert not err, label + ': ' + err
        values[label] = val
    assert len(set(values.values())) == 1, values


# ---------------------------------------------------------------------------
# Contract checker — real tree
# ---------------------------------------------------------------------------

def test_contract_green_on_real_tree(checker):
    ok, report = checker.main()
    failures = [f for f in report if not f['ok']]
    assert ok, failures
    names = {f['check'] for f in report}
    assert {'toggle', 'banner_signature', 'hooks_function', 'version_lockstep'} <= names


# ---------------------------------------------------------------------------
# Contract checker — synthetic trees
# ---------------------------------------------------------------------------

_BANNER_SRC = 'def execute(banners, **kwargs):\n    return banners\n'
_HOOKS_SRC = (
    'def install():\n    return {}\n\n'
    'def pre_update():\n    return {}\n\n'
    'def uninstall():\n    return {}\n'
)


def _make_synthetic_tree(base: Path, version: str):
    '''Build a minimal plugin tree the checker accepts, copy the real
    checker into it, and return the module imported from THAT copy (its
    _plugin_root() resolves to the synthetic tree).'''
    (base / 'scripts').mkdir(parents=True, exist_ok=True)
    (base / 'extensions' / 'python' / 'banners').mkdir(parents=True, exist_ok=True)
    (base / 'extensions' / 'webui' / 'page-head').mkdir(parents=True, exist_ok=True)
    (base / 'webui').mkdir(parents=True, exist_ok=True)
    (base / '.toggle-1').write_text('', encoding='utf-8')
    (base / 'extensions/python/banners/b.py').write_text(_BANNER_SRC, encoding='utf-8')
    (base / 'hooks.py').write_text(_HOOKS_SRC, encoding='utf-8')
    (base / 'version_sync.py').write_text('FALLBACK = ' + repr(version) + '\n', encoding='utf-8')
    (base / 'execute.py').write_text('EXPECTED_VERSION = ' + json.dumps(version) + '\n', encoding='utf-8')
    (base / 'webui/dashboard.js').write_text("versionLabel: 'v" + version + "',\n", encoding='utf-8')
    (base / 'webui/page.html').write_text(
        '<h1>Vibe-Trading <span class="vt-tag">v' + version + '</span></h1>\n', encoding='utf-8')
    (base / 'extensions/webui/page-head/vibe-trading-head.html').write_text(
        '<meta name="vibe-trading-plugin" content="vibe_trading v' + version + '" />\n', encoding='utf-8')
    (base / 'plugin.yaml').write_text('name: vibe_trading\nversion: ' + version + '\n', encoding='utf-8')
    shutil.copy(str(SCRIPTS_DIR / 'check_v22_contract.py'), str(base / 'scripts' / 'check_v22_contract.py'))
    return _import_module(_unique_name('vibe_check_synth'), base / 'scripts' / 'check_v22_contract.py')


def test_synthetic_tree_passes_when_consistent(tmp_path):
    mod = _make_synthetic_tree(tmp_path / 'tree_ok', '0.1.15')
    ok, report = mod.main()
    assert ok, [f for f in report if not f['ok']]


def test_synthetic_tree_catches_version_drift(tmp_path):
    tree = tmp_path / 'tree_drift'
    mod = _make_synthetic_tree(tree, '0.1.15')
    (tree / 'execute.py').write_text('EXPECTED_VERSION = "0.1.14"\n', encoding='utf-8')
    ok, report = mod.main()
    assert not ok
    assert any(f['check'] == 'version_lockstep' for f in report if not f['ok'])


def test_synthetic_tree_catches_disabled_toggle(tmp_path):
    tree = tmp_path / 'tree_off'
    mod = _make_synthetic_tree(tree, '0.1.15')
    (tree / '.toggle-0').write_text('', encoding='utf-8')
    ok, report = mod.main()
    assert not ok
    assert any(f['check'] == 'toggle' for f in report if not f['ok'])


# ---------------------------------------------------------------------------
# hooks._build_mcp_entry — config → MCP entry translation
# ---------------------------------------------------------------------------

def test_entry_hard_invariants(hooks_mod):
    entry = hooks_mod._build_mcp_entry({})
    assert entry['disabled'] is False
    assert entry['init_timeout'] == 30
    assert entry['tool_timeout'] == 300
    assert 'env' not in entry  # empty config → no env block at all


def test_entry_llm_provider_mapping(hooks_mod):
    entry = hooks_mod._build_mcp_entry({
        'llm_provider': 'openrouter',
        'llm_model': 'deepseek/deepseek-v4-pro',
        'temperature': 0.0,
        'timeout_seconds': 120,
    })
    env = entry['env']
    assert env['LANGCHAIN_PROVIDER'] == 'openrouter'
    assert env['LLM_MODEL'] == 'deepseek/deepseek-v4-pro'
    assert env['LANGCHAIN_MODEL_NAME'] == 'deepseek/deepseek-v4-pro'  # legacy alias
    assert env['LANGCHAIN_TEMPERATURE'] == '0.0'
    assert env['TIMEOUT_SECONDS'] == '120'


def test_entry_data_source_passthrough(hooks_mod):
    entry = hooks_mod._build_mcp_entry({
        'tushare_token': 'tok',
        'iwencai_key': 'iw',
        'qveris_api_key': 'qv',
        'qveris_base_url': 'https://q.example',
    })
    env = entry['env']
    assert env['TUSHARE_TOKEN'] == 'tok'
    assert env['VIBE_TRADING_IWENCAI_KEY'] == 'iw'
    assert env['QVERIS_API_KEY'] == 'qv'
    assert env['QVERIS_BASE_URL'] == 'https://q.example'


def test_entry_empty_qveris_absent(hooks_mod):
    entry = hooks_mod._build_mcp_entry({'qveris_api_key': '', 'qveris_base_url': None})
    assert 'QVERIS_API_KEY' not in entry.get('env', {})
    assert 'QVERIS_BASE_URL' not in entry.get('env', {})


def test_entry_data_cache_flags(hooks_mod):
    assert hooks_mod._build_mcp_entry({'data_cache': '1'})['env']['VIBE_TRADING_DATA_CACHE'] == '1'
    assert hooks_mod._build_mcp_entry({'data_cache': 'true'})['env']['VIBE_TRADING_DATA_CACHE'] == '1'
    assert 'VIBE_TRADING_DATA_CACHE' not in hooks_mod._build_mcp_entry({'data_cache': 0}).get('env', {})


def test_entry_risk_tier(hooks_mod):
    entry = hooks_mod._build_mcp_entry({'risk_tier': 'research'})
    assert entry['env']['VIBE_TRADING_RISK_TIER'] == 'research'


def test_entry_market_order_string_normalized(hooks_mod):
    entry = hooks_mod._build_mcp_entry({
        'market_data_order_json': json.dumps({
            'FUTURES': 'akshare,local',
            'us-equity': 'yfinance,stooq',
        }),
    })
    env = entry['env']
    assert env['MARKET_DATA_ORDER_FUTURES'] == 'akshare,local'
    assert env['MARKET_DATA_ORDER_US_EQUITY'] == 'yfinance,stooq'


def test_entry_market_order_dict_accepted(hooks_mod):
    entry = hooks_mod._build_mcp_entry({'market_data_order_json': {'CRYPTO': 'okx,ccxt'}})
    assert entry['env']['MARKET_DATA_ORDER_CRYPTO'] == 'okx,ccxt'


def test_entry_market_order_unknown_market_dropped(hooks_mod):
    entry = hooks_mod._build_mcp_entry({
        'market_data_order_json': json.dumps({'MOON': 'x', 'FUND': 'akshare'}),
    })
    env = entry['env']
    assert 'MARKET_DATA_ORDER_MOON' not in env
    assert env['MARKET_DATA_ORDER_FUND'] == 'akshare'


def test_entry_market_order_empty_and_invalid_ignored(hooks_mod):
    blank = hooks_mod._build_mcp_entry({'market_data_order_json': '{"FUTURES": "   "}'})
    assert 'MARKET_DATA_ORDER_FUTURES' not in blank.get('env', {})  # env may be absent entirely
    broken = hooks_mod._build_mcp_entry({'market_data_order_json': '{"FUTURES": '})
    assert not [k for k in broken.get('env', {}) if k.startswith('MARKET_DATA_ORDER_')]
    empty = hooks_mod._build_mcp_entry({'market_data_order_json': ''})
    assert 'MARKET_DATA_ORDER_FUTURES' not in empty.get('env', {})


def test_entry_absolute_command_trusted(hooks_mod):
    entry = hooks_mod._build_mcp_entry({'mcp_command': '/custom/venv/bin/vibe-trading-mcp'})
    assert entry['command'] == '/custom/venv/bin/vibe-trading-mcp'


# ---------------------------------------------------------------------------
# vibe_trading_cache — TTL semantics
# ---------------------------------------------------------------------------

@pytest.fixture()
def vcache():
    sys.path.insert(0, str(PLUGIN_ROOT))
    import vibe_trading_cache as mod
    mod.flush()
    yield mod
    mod.flush()


def test_cache_set_get_miss(vcache):
    assert vcache.get('k') is None
    vcache.set('k', {'a': 1}, ttl=60.0, now=1000.0)
    assert vcache.get('k', now=1001.0) == {'a': 1}
    assert vcache.get('k', now=2000.0) is None  # expired


def test_cache_ttl_seconds_alias(vcache):
    vcache.set('k', 'v', ttl_seconds=10.0, now=100.0)
    assert vcache.get('k', now=105.0) == 'v'
    assert vcache.get('k', now=120.0) is None


def test_cache_invalidate_wildcard(vcache):
    vcache.set('journal.summary', 1, ttl=60.0, now=0.0)
    vcache.set('journal.kpis', 2, ttl=60.0, now=0.0)
    vcache.set('portfolio.summary', 3, ttl=60.0, now=0.0)
    removed = vcache.invalidate('journal.*')
    assert removed == 2
    assert vcache.get('journal.summary', now=1.0) is None
    assert vcache.get('journal.kpis', now=1.0) is None
    assert vcache.get('portfolio.summary', now=1.0) == 3


def test_cache_invalidate_exact(vcache):
    vcache.set('a.b', 1, ttl=60.0, now=0.0)
    assert vcache.invalidate('a.b') == 1
    assert vcache.get('a.b', now=1.0) is None


def test_cache_fresh_loader_once(vcache):
    calls = []

    def loader():
        calls.append(1)
        return {'n': len(calls)}

    v1, c1 = vcache.fresh('x', 60.0, loader)
    v2, c2 = vcache.fresh('x', 60.0, loader)
    assert c1 is False and c2 is True
    assert v1 == v2 == {'n': 1}
    assert len(calls) == 1


def test_cache_stats_counts(vcache):
    vcache.set('s', 1, ttl=60.0, now=0.0)
    vcache.get('s', now=1.0)      # hit
    vcache.get('missing', now=1.0)  # miss
    st = vcache.stats()
    assert st['sets'] >= 1 and st['hits'] >= 1 and st['misses'] >= 1
    assert st['size'] >= 1


# ---------------------------------------------------------------------------
# Source-contract guards (modules that import helpers.api can't be imported
# outside the A0 runtime — assert the patterns in source instead)
# ---------------------------------------------------------------------------

def test_shadow_cache_keys_on_journal_hash():
    src = (PLUGIN_ROOT / 'api' / 'shadow.py').read_text(encoding='utf-8')
    assert 'import hashlib' in src
    assert 'hashlib.sha256' in src
    assert 'journal_sha' in src
    # the hash must be part of the cache key tuple, not just computed
    assert re.search(r"cache_key\s*=\s*\(journal_path,\s*journal_sha", src)


def test_portfolio_has_upstream_cli_fallback():
    src = (PLUGIN_ROOT / 'api' / 'portfolio.py').read_text(encoding='utf-8')
    assert 'portfolio', 'show'  # sanity on the file itself
    assert "'portfolio', 'show'" in src or "['portfolio', 'show']" in src
    assert '_vibe_cli_path' in src
    assert "'refresh'" in src and "'sources'" in src


def test_default_config_qveris_defaults_off():
    cfg = yaml.safe_load((PLUGIN_ROOT / 'default_config.yaml').read_text(encoding='utf-8'))
    assert cfg.get('qveris_api_key') == ''
    assert cfg.get('qveris_base_url') == ''
    assert cfg.get('market_data_order_json') == '{}'
    assert cfg.get('mcp_enabled') is True


def test_config_json_pins_absolute_mcp_command():
    '''The two-venv trap (AGENTS.md, incident 2026-09-22): without an
    absolute mcp_command the boot hook registers whichever venv owns the
    app process's PATH. This pin is load-bearing — do not remove.'''
    import json as _json
    cfg = _json.loads((PLUGIN_ROOT / 'config.json').read_text(encoding='utf-8'))
    cmd = cfg.get('mcp_command') or ''
    assert cmd.startswith('/'), 'mcp_command must be an absolute path (two-venv trap)'
    assert cmd.endswith('vibe-trading-mcp')


def test_config_json_user_prefs_preserved():
    '''The pinned mcp_command was added to an existing user config; the
    other keys must survive every future edit.'''
    import json as _json
    cfg = _json.loads((PLUGIN_ROOT / 'config.json').read_text(encoding='utf-8'))
    assert cfg.get('auto_load_uploads') is True
    assert cfg.get('mcp_enabled') is True
    assert cfg.get('require_explicit_confirmation') is True
    assert cfg.get('data_cache') in (True, 1, '1', 'true')


def test_hooks_maps_gildata_env():
    src = (PLUGIN_ROOT / 'hooks.py').read_text(encoding='utf-8')
    assert '("gildata_token", "GILDATA_TOKEN")' in src
    assert '("gildata_base_url", "GILDATA_BASE_URL")' in src


def test_default_config_has_gildata_keys():
    cfg = yaml.safe_load((PLUGIN_ROOT / 'default_config.yaml').read_text(encoding='utf-8'))
    assert cfg.get('gildata_token') == ''
    assert cfg.get('gildata_base_url') == ''
