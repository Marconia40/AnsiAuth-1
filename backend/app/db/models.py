from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True, index=True)
    email = Column(String, nullable=True, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    is_system_admin = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("username", name="uq_user_username"),
        UniqueConstraint("email", name="uq_user_email"),
    )


class DeviceModel(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True, index=True)
    host = Column(String, nullable=False)
    vendor = Column(String, nullable=False)
    platform = Column(String, nullable=True)
    username = Column(String, nullable=False)
    encrypted_password = Column(String, nullable=False)
    auth_method = Column(String, nullable=False, server_default="password")
    encrypted_private_key = Column(Text, nullable=True)
    device_group_id = Column(
        Integer,
        ForeignKey(
            "device_groups.id", use_alter=True, name="fk_devices_device_group_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    vlans_synced_at = Column(DateTime(timezone=True), nullable=True)
    vlans_sync_error = Column(Text, nullable=True)
    ports_synced_at = Column(DateTime(timezone=True), nullable=True)
    ports_sync_error = Column(Text, nullable=True)
    svis_synced_at = Column(DateTime(timezone=True), nullable=True)
    svis_sync_error = Column(Text, nullable=True)
    global_config_synced_at = Column(DateTime(timezone=True), nullable=True)
    global_config_sync_error = Column(Text, nullable=True)
    arp_mac_synced_at = Column(DateTime(timezone=True), nullable=True)
    arp_mac_sync_error = Column(Text, nullable=True)
    logs_synced_at = Column(DateTime(timezone=True), nullable=True)
    logs_sync_error = Column(Text, nullable=True)

    device_group = relationship(
        "DeviceGroupModel",
        foreign_keys=[device_group_id],
        uselist=False,
    )

    __table_args__ = (UniqueConstraint("name", name="uq_device_name"),)


class DeviceVlanModel(Base):
    __tablename__ = "device_vlans"

    vlan_id = Column(Integer, primary_key=True)
    device = Column(
        String,
        ForeignKey("devices.name", ondelete="CASCADE"),
        primary_key=True,
    )
    name = Column(String, nullable=False)


class DevicePortModel(Base):
    __tablename__ = "device_ports"

    interface = Column(String, primary_key=True)
    device = Column(
        String,
        ForeignKey("devices.name", ondelete="CASCADE"),
        primary_key=True,
    )
    description = Column(String, nullable=True)
    admin_up = Column(Boolean, nullable=True)
    mode = Column(String, nullable=True)
    access_vlan = Column(Integer, nullable=True)
    allowed_vlans = Column(JSON, nullable=True)
    poe_enabled = Column(Boolean, nullable=True)
    storm_control_enabled = Column(Boolean, nullable=True)
    storm_control_threshold = Column(Float, nullable=True)
    storm_control_action = Column(String, nullable=True)
    storm_control_trap = Column(Boolean, nullable=True)
    operational_up = Column(Boolean, nullable=True)
    speed = Column(String, nullable=True)
    duplex = Column(String, nullable=True)
    kind = Column(String, nullable=False, server_default="physical")


class DeviceSVIModel(Base):
    __tablename__ = "device_svis"

    vlan_id = Column(Integer, primary_key=True)
    device = Column(
        String,
        ForeignKey("devices.name", ondelete="CASCADE"),
        primary_key=True,
    )
    description = Column(String, nullable=True)
    admin_up = Column(Boolean, nullable=True)
    ipv4_address = Column(String, nullable=True)
    ipv4_address_secondary = Column(JSON, nullable=True)
    ipv6_address = Column(String, nullable=True)
    acl_in = Column(String, nullable=True)
    acl_out = Column(String, nullable=True)
    dhcp_relay_servers = Column(JSON, nullable=True)
    operational_up = Column(Boolean, nullable=True)


class DeviceGlobalConfigModel(Base):
    __tablename__ = "device_global_config"

    device = Column(
        String,
        ForeignKey("devices.name", ondelete="CASCADE"),
        primary_key=True,
    )
    hostname = Column(String, nullable=True)
    running_config = Column(Text, nullable=True)
    device_version = Column(String, nullable=True)
    snmp_enabled = Column(Boolean, nullable=True)
    snmp_version = Column(String, nullable=True)
    snmp_community = Column(String, nullable=True)
    snmp_permission = Column(String, nullable=True)
    snmp_trap_hosts = Column(JSON, nullable=True)
    ntp_servers = Column(JSON, nullable=True)
    dns_servers = Column(JSON, nullable=True)
    log_servers = Column(JSON, nullable=True)
    log_level = Column(String, nullable=True)
    routes = Column(JSON, nullable=True)
    acls = Column(JSON, nullable=True)


class DeviceArpMacModel(Base):
    __tablename__ = "device_arp_mac"

    device = Column(
        String,
        ForeignKey("devices.name", ondelete="CASCADE"),
        primary_key=True,
    )
    arp_table = Column(JSON, nullable=True)
    mac_table = Column(JSON, nullable=True)


class DeviceLogsModel(Base):
    __tablename__ = "device_logs"

    device = Column(
        String,
        ForeignKey("devices.name", ondelete="CASCADE"),
        primary_key=True,
    )
    log_output = Column(Text, nullable=True)


class JobModel(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    operation = Column(String, nullable=True)
    playbook = Column(String, nullable=True)
    device = Column(String, nullable=True)
    parameters = Column(JSON, nullable=True)
    parameters_summary = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)
    rollback_performed = Column(Boolean, nullable=False, default=False)
    rollback_success = Column(Boolean, nullable=True)
    pre_state = Column(JSON, nullable=True)
    last_error = Column(Text, nullable=True)
    error_type = Column(String, nullable=True)
    error_reason = Column(String, nullable=True)
    error_summary = Column(Text, nullable=True)
    rollback_error = Column(Text, nullable=True)
    current_step = Column(String, nullable=True)
    group_job_id = Column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_jobs_status_created_at", "status", "created_at"),
    )


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    username = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=False)
    session_id = Column(String, nullable=False, index=True)
    session_started_at = Column(DateTime(timezone=True), nullable=False)
    parent_id = Column(Integer, ForeignKey("refresh_tokens.id"), nullable=True, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)


class LoginAttemptModel(Base):
    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, index=True)
    ip_address = Column(String, nullable=False, index=True)
    attempted_at = Column(DateTime(timezone=True), nullable=False, index=True)
    succeeded = Column(Boolean, nullable=False, default=False)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    user = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, index=True)
    resource = Column(String, nullable=False, index=True)
    resource_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="success")
    details = Column(JSON, nullable=False, default=dict)
    summary = Column(Text, nullable=True)
    job_id = Column(String, nullable=True)
    device = Column(String, nullable=True)
    request_id = Column(String, nullable=True)
    parent_audit_id = Column(Integer, ForeignKey("audit_logs.id"), nullable=True, index=True)


class DeviceGroupModel(Base):
    __tablename__ = "device_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    site_id = Column(
        Integer,
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    is_default = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    site = relationship(
        "SiteModel",
        back_populates="device_groups",
        foreign_keys=[site_id],
    )

    __table_args__ = (
        UniqueConstraint("site_id", "name", name="uq_device_group_site_name"),
    )


class SiteModel(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(String, nullable=True)
    kind = Column(
        String(32), nullable=False, default="REGULAR", server_default="REGULAR"
    )
    default_group_id = Column(
        Integer,
        ForeignKey(
            "device_groups.id", use_alter=True, name="fk_sites_default_group_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    device_groups = relationship(
        "DeviceGroupModel",
        back_populates="site",
        foreign_keys="DeviceGroupModel.site_id",
    )
    default_group = relationship(
        "DeviceGroupModel",
        foreign_keys=[default_group_id],
        post_update=True,
        uselist=False,
    )

    __table_args__ = (UniqueConstraint("name", name="uq_site_name"),)


class RoleAssignmentModel(Base):
    __tablename__ = "role_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    site_id = Column(
        Integer,
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_group_id = Column(
        Integer,
        ForeignKey("device_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role = Column(String(32), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user = relationship("UserModel", foreign_keys=[user_id])
    created_by = relationship("UserModel", foreign_keys=[created_by_user_id])
    site = relationship("SiteModel")
    device_group = relationship("DeviceGroupModel")

    __table_args__ = (
        CheckConstraint(
            "role IN ('observer', 'operator', 'admin')",
            name="ck_role_assignments_role",
        ),
        UniqueConstraint(
            "user_id",
            "site_id",
            "device_group_id",
            name="uq_role_assignments_scope",
        ),
    )
