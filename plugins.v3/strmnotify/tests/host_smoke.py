"""在隔离 MoviePilot 环境执行的模拟通知验证，不向外部发送消息"""
import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from app.testing.bootstrap import prepare_backend
prepare_backend()
spec=importlib.util.spec_from_file_location('strmnotify',str(Path(__file__).resolve().parents[1] / '__init__.py'),submodule_search_locations=[str(Path(__file__).resolve().parents[1])])
import sys
module=importlib.util.module_from_spec(spec);sys.modules['strmnotify']=module;spec.loader.exec_module(module)
with patch.object(module._PluginBase, "__init__", return_value=None):
 plugin=module.StrmNotify()
storage={}
plugin.get_data=lambda key:json.loads(json.dumps(storage.get(key)))
plugin.save_data=Mock(side_effect=lambda key,value:storage.update({key:json.loads(json.dumps(value))}))
plugin.post_message=Mock()
with TemporaryDirectory() as directory:
 root=Path(directory)
 (root/'old.strm').touch()
 plugin.init_plugin({'enabled':True,'paths':str(root),'batch':1,'wait':120})
 assert plugin.get_state() and len(plugin.get_service())==1
 plugin.get_form()
 plugin.poll();assert plugin.post_message.call_count==0
 assert plugin.save_data.call_count==1
 plugin.save_data.reset_mock()
 plugin.poll();assert plugin.save_data.call_count==0
 for name in ['one','two']:
  (root/f'{name}.strm').touch()
  cover = '<thumb>https://example.invalid/one.jpg</thumb>' if name == 'one' else ''
  p=root/f'{name}.nfo';p.write_text(f'<movie><title>{name}</title>{cover}</movie>');os.utime(p,(0,0))
 plugin.poll();assert plugin.post_message.call_count==1
 assert str(root.resolve()/'two.strm') in storage['state'][str(root.resolve())]['pending']
 with patch.object(module, 'time', return_value=module.time()+121):
  plugin.poll()
 assert plugin.post_message.call_count==2
 assert any(call.kwargs.get('image') is None for call in plugin.post_message.call_args_list)
 plugin.init_plugin({'enabled':True,'paths':str(root)})
 plugin.poll();assert plugin.post_message.call_count==2
 plugin.save_data.reset_mock()
 plugin.poll();assert plugin.save_data.call_count==0
 waiting=root/'waiting.strm';waiting.touch()
 plugin.poll();assert plugin.save_data.call_count==1
 plugin.save_data.reset_mock()
 plugin.poll();assert plugin.save_data.call_count==0
 with patch.object(module, 'time', return_value=module.time()+121):
  plugin.poll()
 assert plugin.save_data.call_count==1
 assert not storage['state'][str(root.resolve())]['pending']
 retry=root/'retry.strm';retry.touch()
 retry_nfo=retry.with_suffix('.nfo');retry_nfo.write_text('<movie><title>retry</title><thumb>https://example.invalid/retry.jpg</thumb></movie>');os.utime(retry_nfo,(0,0))
 plugin.post_message.side_effect=RuntimeError('simulated failure')
 plugin.poll()
 assert str(retry.resolve()) in storage['state'][str(root.resolve())]['pending']
 plugin.save_data.reset_mock();plugin.poll();assert plugin.save_data.call_count==0
 plugin.post_message.side_effect=None
 plugin.poll();assert not storage['state'][str(root.resolve())]['pending']
 delivered=plugin.post_message.call_count
 plugin.stop_service();(root/'three.strm').touch();plugin.poll();assert plugin.post_message.call_count==delivered
print('PASS: real MP plugin load/form/service; baseline; batch; persisted dedup; disable; unchanged scans write zero times; waiting, timeout and retry persistence; mocked delivery only')
