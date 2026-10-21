"""Retired identity entry points must fail explicitly, never fabricate names."""
import json

import pytest

from centerstage.智能识别引擎 import SmartIdentifier
from centerstage.智能识别集成 import auto_identify_members, apply_names_to_frames


def test_salience_and_roster_order_are_not_identity_evidence(tmp_path):
    identifier=SmartIdentifier(tmp_path)
    identifier.roster=['Example A','Example B']
    with pytest.raises(ValueError):identifier.auto_match_tracks({'a':{'center_time':100}})
    with pytest.raises(ValueError):auto_identify_members(object(),object())
    with pytest.raises(ValueError):apply_names_to_frames(object(),identifier)
    assert identifier.get_all_mappings()=={}


def test_legacy_guess_cache_cannot_reenter_current_labels(tmp_path):
    payload={'roster':['Example'],'mappings':{'a':'Example'},'confidence':{'a':1}}
    (tmp_path/'clip_smart_id.json').write_text(json.dumps(payload))
    identifier=SmartIdentifier(tmp_path)
    assert identifier.load('clip') is False and identifier.track_mappings=={}
    assert json.loads((tmp_path/'clip_smart_id.json').read_text())==payload


def test_explicit_user_correction_survives_cache_reload(tmp_path):
    identifier=SmartIdentifier(tmp_path)
    identifier.manual_correction('a','Example');identifier.save('clip')
    restored=SmartIdentifier(tmp_path)
    assert restored.load('clip')
    assert restored.get_member_name('a')=='Example'
    assert restored.evidence=={'a':'user_confirmed'}
