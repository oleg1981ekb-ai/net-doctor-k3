"""Configuration models for awg-ctl."""

from ipaddress import IPv4Network
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServerConfig(BaseModel):
    """Configuration for a single server in the cascade."""

    model_config = ConfigDict(frozen=True)

    host: str
    port: int = Field(default=22, ge=1, le=65535)
    username: str
    ssh_key_path: str | None = None


class NetworkConfig(BaseModel):
    """WireGuard/AmneziaWG network parameters."""

    model_config = ConfigDict(frozen=True)

    client_subnet: IPv4Network
    link1_subnet: IPv4Network
    link2_subnet: IPv4Network
    mtu: int = Field(default=1360, ge=1280, le=9000)
    mss_clamp: bool = True
    persistent_keepalive: int = Field(default=25, ge=0, le=120)
    dns: list[str] = Field(min_length=1)
    ip_checker_url: str = Field(min_length=1)


class SysctlConfig(BaseModel):
    """sysctl settings applied on all nodes."""

    model_config = ConfigDict(frozen=True, extra="allow")

    net_ipv4_ip_forward: int = Field(default=1, ge=0, le=1)
    net_ipv4_conf_all_rp_filter: int = Field(default=2, ge=0, le=2)
    net_netfilter_nf_conntrack_max: int = Field(default=65536, gt=0)
    net_ipv6_conf_all_disable_ipv6: int = Field(default=1, ge=0, le=1)


class PortsConfig(BaseModel):
    """UDP port assignments."""

    model_config = ConfigDict(frozen=True)

    client_in: int = Field(ge=10000, le=59999)
    link1: int = Field(ge=10000, le=59999)
    link2: int = Field(ge=10000, le=59999)
    mobile: int | None = Field(default=None)


class ScriptsConfig(BaseModel):
    """Paths to helper scripts on the server."""

    model_config = ConfigDict(frozen=True)

    manage_amneziawg: str = Field(default="/root/awg/manage_amneziawg.sh")
    routing: str = Field(default="/root/awg/awg-routing.sh")
    backup_prefixes: str = Field(default="/root/awg/ru.zone")


class TimeoutsConfig(BaseModel):
    """Timeouts in seconds."""

    model_config = ConfigDict(frozen=True)

    ssh_connect: int = Field(default=10, gt=0)
    ssh_command: int = Field(default=30, gt=0)
    deploy: int = Field(default=600, gt=0)
    check: int = Field(default=60, gt=0)


class CheckConfig(BaseModel):
    """Allowed keepalive range for the check command."""

    model_config = ConfigDict(frozen=True)

    keepalive_min: int = Field(default=1, ge=1, le=120)
    keepalive_max: int = Field(default=33, ge=0, le=120)

    @model_validator(mode="after")
    def _check_keepalive_range(self) -> "CheckConfig":
        if self.keepalive_min > self.keepalive_max:
            raise ValueError("keepalive_min must be <= keepalive_max")
        return self


class CascadeConfig(BaseModel):
    """Root configuration model for awg-ctl cascade."""

    model_config = ConfigDict(frozen=True)

    servers: dict[Literal["in", "mid", "out"], ServerConfig]
    network: NetworkConfig
    sysctl: SysctlConfig = Field(default_factory=lambda: SysctlConfig())
    ports: PortsConfig
    scripts: ScriptsConfig = Field(default_factory=lambda: ScriptsConfig())
    timeouts: TimeoutsConfig = Field(default_factory=lambda: TimeoutsConfig())
    check: CheckConfig = Field(default_factory=lambda: CheckConfig())
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @staticmethod
    def load(path: str | Path) -> "CascadeConfig":
        """Load and validate cascade.yaml from a file path."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return CascadeConfig.model_validate(data)

    def validate(self) -> None:
        """Cross-field validation."""
        for key in ("in", "mid", "out"):
            if key not in self.servers:
                raise ValueError(f"Missing required server: {key}")
        if not self.network.dns:
            raise ValueError("At least one DNS resolver is required")
        if not self.network.ip_checker_url.startswith("http"):
            raise ValueError("ip_checker_url must start with http")

        subnets = [
            self.network.client_subnet,
            self.network.link1_subnet,
            self.network.link2_subnet,
        ]
        for i, a in enumerate(subnets):
            for j, b in enumerate(subnets[i + 1 :], start=i + 1):
                if a.overlaps(b):
                    raise ValueError(f"Subnets {a} and {b} overlap")
