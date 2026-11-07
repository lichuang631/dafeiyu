import json
from pathlib import Path

root = Path('/opt/dafeiyu')
path = root / 'data/cmd_config.json'
config = json.loads(path.read_text(encoding='utf-8-sig'))
config['dashboard']['host'] = '0.0.0.0'
for platform in config.get('platform', []):
    if platform.get('type') == 'aiocqhttp' or 'ws_reverse_host' in platform:
        platform['ws_reverse_host'] = '0.0.0.0'
assert config['admins_id'] == ['100000001']
assert config['provider_tts_settings']['trigger_probability'] == 0.6
path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding='utf-8')

folder = root / 'napcat/config'
for path in folder.glob('onebot11*.json'):
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    for client in config.get('network', {}).get('websocketClients', []):
        if client.get('name') == 'AstrBot':
            client['url'] = 'ws://astrbot:6199/ws'
    path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding='utf-8')
path = folder / 'webui.json'
config = json.loads(path.read_text(encoding='utf-8-sig'))
config['host'] = '0.0.0.0'
config['autoLoginAccount'] = '100000002'
path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding='utf-8')
print('云端网络配置已转换；主人、模型及语音配置已保留。')
