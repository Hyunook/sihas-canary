"""Manual setup gets the same unique_id as DHCP discovery, so IP changes are followed."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sihas.config_flow import discovery_mac
from custom_components.sihas.const import DOMAIN
from custom_components.sihas.util import MacConv

SIHAS_MAC = "a8:2b:d6:e7:d5:05"
ESPRESSIF_MAC = "e8:68:e7:e7:d5:05"  # the same module seen with its factory OUI


def scan_reply(mac: str, ip: str = "192.168.050.158") -> str:
    message = f"SiHAS_BCM_v1.035_MAC_{mac}_IP_{ip}_CFG_00"
    assert message[21:38] == mac and message[42:57] == ip  # util.parse_scan_message layout
    return message


USER_INPUT = {"ip": "192.168.50.158", "type": "BCM", "cfg": 0, "name": "BCM-300 보일러제어기"}


async def _user_flow(hass, reply, user_input=USER_INPUT):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.sihas.config_flow.scan", return_value=reply) as scan:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    scan.assert_called_once()
    return result


@pytest.mark.parametrize("mac", [SIHAS_MAC, ESPRESSIF_MAC, SIHAS_MAC.upper()])
def test_discovery_mac_matches_dhcp_and_zeroconf(mac):
    dhcp_unique_id = MacConv.insert_colon("a82bd6e7d505")  # DhcpServiceInfo.macaddress form
    zeroconf_mac = MacConv.insert_colon("a82bd6" + "e7d505").lower()
    assert discovery_mac(mac) == dhcp_unique_id == zeroconf_mac == SIHAS_MAC


async def test_manual_entry_gets_unique_id(hass, enable_custom_integrations):
    with patch("custom_components.sihas.async_setup_entry", return_value=True):
        result = await _user_flow(hass, scan_reply(SIHAS_MAC))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SIHAS_MAC
    assert result["data"]["mac"] == SIHAS_MAC
    assert result["data"]["ip"] == "192.168.50.158"


async def test_manual_entry_updates_ip_of_existing_device(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SIHAS_MAC,
        data={"ip": "192.168.50.159", "mac": SIHAS_MAC, "type": "BCM", "cfg": 0, "name": "x"},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.sihas.async_setup_entry", return_value=True):
        result = await _user_flow(
            hass, scan_reply(ESPRESSIF_MAC), {**USER_INPUT, "mac": ESPRESSIF_MAC}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["ip"] == "192.168.50.158"


async def test_manual_entry_requires_scan_reply(hass, enable_custom_integrations):
    result = await _user_flow(hass, None)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_dhcp_discovery_matches_manual_entry(hass, enable_custom_integrations):
    with patch("custom_components.sihas.async_setup_entry", return_value=True):
        await _user_flow(hass, scan_reply(SIHAS_MAC))
    with (
        patch("custom_components.sihas.config_flow.asyncio.sleep", new=AsyncMock()),
        patch("custom_components.sihas.config_flow.scan", return_value=scan_reply(SIHAS_MAC)),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_DHCP},
            data=DhcpServiceInfo(
                ip="192.168.50.160", hostname="esp-e7d505", macaddress="a82bd6e7d505"
            ),
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["ip"] == "192.168.50.160"
