"""Tests for configuration loading and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from awg_cascade_ctl.config import CascadeConfig

VALID_YAML = """
servers:
  in:
    host: vpn-in.example.com
    port: 22
    username: root
  mid:
    host: vpn-mid.example.com
    port: 22
    username: root
  out:
    host: vpn-out.example.com
    port: 22
    username: root
network:
  client_subnet: 10.9.9.0/24
  link1_subnet: 10.10.1.0/30
  link2_subnet: 10.10.2.0/30
  mtu: 1360
  mss_clamp: true
  persistent_keepalive: 25
  dns:
    - 1.1.1.1
    - 9.9.9.9
  ip_checker_url: https://api.ipify.org
ports:
  client_in: 51820
  link1: 51821
  link2: 51822
  mobile: 443
"""


def test_load_valid_config(tmp_path: Path) -> None:
    """Valid YAML should parse without errors."""
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(VALID_YAML)
    cfg = CascadeConfig.load(cfg_path)
    assert cfg.servers["in"].host == "vpn-in.example.com"
    assert str(cfg.network.client_subnet) == "10.9.9.0/24"
    assert cfg.ports.client_in == 51820


def test_missing_required_field(tmp_path: Path) -> None:
    """Missing required field should raise ValidationError."""
    yaml_content = VALID_YAML.replace("client_subnet: 10.9.9.0/24", "")
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(yaml_content)
    with pytest.raises(ValidationError):
        CascadeConfig.load(cfg_path)


def test_overlapping_subnets(tmp_path: Path) -> None:
    """Overlapping subnets should raise during validate()."""
    yaml_content = VALID_YAML.replace(
        "link1_subnet: 10.10.1.0/30",
        "link1_subnet: 10.9.9.0/24",
    )
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(yaml_content)
    cfg = CascadeConfig.load(cfg_path)
    with pytest.raises(ValueError, match="overlap"):
        cfg.validate()


def test_invalid_port_range(tmp_path: Path) -> None:
    """Port outside valid range should raise ValidationError."""
    yaml_content = VALID_YAML.replace("client_in: 51820", "client_in: 99999")
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(yaml_content)
    with pytest.raises(ValidationError):
        CascadeConfig.load(cfg_path)


def test_missing_server(tmp_path: Path) -> None:
    """Missing one of the three required servers should raise."""
    yaml_content = VALID_YAML.replace(
        "  out:\n    host: vpn-out.example.com\n    port: 22\n    username: root\n",
        "",
    )
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(yaml_content)
    cfg = CascadeConfig.load(cfg_path)
    with pytest.raises(ValueError, match="Missing required server"):
        cfg.validate()


def test_invalid_ip_checker_url(tmp_path: Path) -> None:
    """Non-HTTP URL should fail validation."""
    yaml_content = VALID_YAML.replace(
        "ip_checker_url: https://api.ipify.org",
        "ip_checker_url: ftp://example.com",
    )
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(yaml_content)
    cfg = CascadeConfig.load(cfg_path)
    with pytest.raises(ValueError, match="http"):
        cfg.validate()


def test_config_is_frozen(tmp_path: Path) -> None:
    """CascadeConfig instances should be immutable."""
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(VALID_YAML)
    cfg = CascadeConfig.load(cfg_path)
    with pytest.raises(ValidationError):
        cfg.servers["in"].host = "new-host"