#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import re
import subprocess
import sys

import paramiko
import telnetlib3
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

ARISTA_HOST = os.getenv("ARISTA_HOST")
ARISTA_PORT = int(os.getenv("ARISTA_PORT", "22"))
ARISTA_USERNAME = os.getenv("ARISTA_USERNAME")
ARISTA_PASSWORD = os.getenv("ARISTA_PASSWORD")

IMG_USERNAME = os.getenv("IMG_USERNAME", "admin")
IMG_PASSWORD = os.getenv("IMG_PASSWORD")
IMG_ENABLE_PASSWORD = os.getenv("IMG_ENABLE_PASSWORD", "")

TELNET_PORT = int(os.getenv("TELNET_PORT", "23"))
TIMEOUT = int(os.getenv("TIMEOUT", "12"))

LOG_FILE = "img_reboot.log"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)

log = logging.getLogger(__name__)


# ============================================================
# MAC ADDRESS NORMALIZATION
# ============================================================

def normalize_mac(mac):
    mac = re.sub(r"[^0-9a-fA-F]", "", mac)

    if len(mac) != 12:
        raise ValueError("Invalid MAC address")

    mac = mac.upper()

    return ":".join(
        mac[i:i + 2] for i in range(0, 12, 2)
    )


# ============================================================
# ARISTA ARP LOOKUP
# ============================================================

def find_ip_on_arista(mac):

    log.info("Connecting to Arista: %s", ARISTA_HOST)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    try:
        client.connect(
            hostname=ARISTA_HOST,
            port=ARISTA_PORT,
            username=ARISTA_USERNAME,
            password=ARISTA_PASSWORD,
            timeout=TIMEOUT,
            auth_timeout=TIMEOUT,
            banner_timeout=TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )

        command = f"show arp mac-address {mac}"

        stdin, stdout, stderr = client.exec_command(
            command,
            timeout=TIMEOUT,
        )

        output = stdout.read().decode(
            "utf-8", errors="ignore"
        )

        error_output = stderr.read().decode(
            "utf-8", errors="ignore"
        )

        exit_status = stdout.channel.recv_exit_status()

        if exit_status != 0:
            raise RuntimeError(
                error_output.strip() or
                "Arista command failed"
            )

        log.info("Arista ARP lookup complete")

        target_mac = normalize_mac(mac).replace(":", "")

        for line in output.splitlines():

            line_mac = re.sub(
                r"[^0-9a-fA-F]", "", line
            ).upper()

            if target_mac in line_mac:

                ips = re.findall(
                    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
                    line,
                )

                if ips:
                    log.info("MAC found: %s", ips[0])
                    return ips[0]

        log.error("MAC address not found in Arista ARP table")
        return None

    finally:
        client.close()


# ============================================================
# PING CHECK
# ============================================================

def ping_device(ip):

    log.info("Checking connectivity to iMG: %s", ip)

    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )

        if result.returncode == 0:
            log.info("PING SUCCESS: %s is reachable", ip)
            return True

        log.error("PING FAILED: %s is not responding", ip)
        return False

    except subprocess.TimeoutExpired:
        log.error("PING TIMEOUT: %s", ip)
        return False

    except FileNotFoundError:
        log.error("PING command not found on this system")
        return False

    except Exception as exc:
        log.error("PING ERROR: %s", exc)
        return False


async def wait_for_ping_state(ip, expected_online, timeout, interval):

    log.info(
        "Waiting for %s to become %s (timeout: %s seconds)",
        ip,
        "reachable" if expected_online else "offline",
        timeout,
    )

    deadline = asyncio.get_running_loop().time() + timeout

    while asyncio.get_running_loop().time() < deadline:

        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )

            online = result.returncode == 0

            if online == expected_online:
                return True

        except Exception:
            pass

        await asyncio.sleep(interval)

    return False

# ============================================================
# TELNET PROMPT READER
# ============================================================

async def read_until_any(reader, prompts, timeout=TIMEOUT):

    collected = ""
    deadline = asyncio.get_running_loop().time() + timeout

    while True:

        remaining = deadline - asyncio.get_running_loop().time()

        if remaining <= 0:
            raise TimeoutError(
                f"Timed out waiting for prompt: {prompts}"
            )

        char = await asyncio.wait_for(
            reader.read(1),
            timeout=remaining,
        )

        if not char:
            raise ConnectionError(
                "Telnet connection closed unexpectedly"
            )

        collected += char
        lower_text = collected.lower()

        for prompt in prompts:
            if prompt.lower() in lower_text:
                return collected, prompt

        # Prevent unlimited output accumulation.
        if len(collected) > 10000:
            collected = collected[-5000:]


# ============================================================
# CONNECT AND LOGIN TO IMG
# ============================================================

async def connect_img(ip):

    log.info("Connecting to Allied Telesis: %s", ip)

    reader = None
    writer = None

    try:
        reader, writer = await telnetlib3.open_connection(
            host=ip,
            port=TELNET_PORT,
            encoding="utf8",
        )

        log.info("Telnet connection established")

        # Wait for login prompt.
        await read_until_any(
            reader,
            ["Login:"],
        )

        writer.write(IMG_USERNAME + "\n")
        await writer.drain()

        # Wait for password prompt.
        await read_until_any(
            reader,
            ["Password:"],
        )

        writer.write((IMG_PASSWORD or "") + "\n")
        await writer.drain()

        # Wait for normal or privileged prompt.
        _, prompt = await read_until_any(
            reader,
            ["awplus>", "awplus#"],
        )

        # Enter privileged mode if needed.
        if prompt.lower() == "awplus>":

            log.info("Entering privileged mode")

            writer.write("enable\n")
            await writer.drain()

            _, prompt = await read_until_any(
                reader,
                ["Password:", "awplus#"],
            )

            if prompt.lower() == "password:":

                writer.write(
                    (IMG_ENABLE_PASSWORD or "") + "\n"
                )
                await writer.drain()

                await read_until_any(
                    reader,
                    ["awplus#"],
                )

        log.info("Successfully logged into %s", ip)

        return reader, writer

    except Exception:

        if writer:
            writer.close()

        raise


# ============================================================
# REBOOT IMG
# ============================================================


async def reboot_img(ip, dry_run=False):

    reader = None
    writer = None

    try:
        reader, writer = await connect_img(ip)

        if dry_run:
            log.info("DRY RUN: Login successful")
            log.info("DRY RUN: No reboot command sent")
            return True

        log.warning("Sending reboot command to %s", ip)

        writer.write("reboot\n")
        await writer.drain()

        # Wait for the exact reboot confirmation prompt.
        await read_until_any(
            reader,
            ["reboot system? (y/n)"],
        )

        log.info("Reboot confirmation prompt received")

        # Confirm reboot.
        writer.write("y\n")
        await writer.drain()

        log.warning("Reboot confirmation sent")

        # Verify that the switch acknowledges the reboot.
        try:
            await read_until_any(
                reader,
                ["Rebooting the Switch"],
                timeout=20,
            )

            log.info("iMG confirmed: Rebooting the Switch")

        except Exception as exc:
            log.error(
                "Reboot acknowledgment not received: %s",
                exc,
            )
            return False

        # Wait for the switch to stop responding to ping.
        log.info("Waiting for iMG to go offline")

        went_offline = await wait_for_ping_state(
            ip,
            expected_online=False,
            timeout=60,
            interval=3,
        )

        if not went_offline:
            log.error(
                "REBOOT NOT VERIFIED: iMG never went offline"
            )
            return False

        log.info("iMG is offline. Reboot confirmed.")

        # Allow up to five minutes for the switch to return.
        log.info("Waiting for iMG to return online (up to 5 minutes)")

        returned_online = await wait_for_ping_state(
            ip,
            expected_online=True,
            timeout=300,
            interval=5,
        )

        if not returned_online:
            log.error(
                "REBOOT INCOMPLETE: iMG did not return "
                "within 5 minutes"
            )
            return False

        log.info("=" * 50)
        log.info("REBOOT VERIFIED: %s is back online", ip)
        log.info("=" * 50)

        return True

    finally:
        if writer:
            writer.close()
            log.info("Telnet connection closed")

# ============================================================
# MAIN WORKFLOW
# ============================================================


async def main():

    parser = argparse.ArgumentParser(
        description="Allied Telesis iMG reboot utility"
    )

    parser.add_argument(
        "macs",
        nargs="+",
        help="One or more MAC addresses",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Connect and log in without rebooting",
    )

    args = parser.parse_args()

    log.info("=" * 50)
    log.info("Starting reboot workflow for %d device(s)", len(args.macs))

    overall_success = True

    for supplied_mac in args.macs:

        try:
            mac = normalize_mac(supplied_mac)

            log.info("-" * 50)
            log.info("Processing MAC: %s", mac)

            ip = find_ip_on_arista(mac)

            if not ip:
                log.error("STOPPING: Unable to find device IP for %s", mac)
                overall_success = False
                continue

            print()
            print("MAC ADDRESS: {}".format(mac))
            print("DEVICE IP:   {}".format(ip))
            print()

            if not ping_device(ip):
                log.error(
                    "STOPPING: %s did not respond to ping. "
                    "Skipping this device.",
                    ip,
                )
                overall_success = False
                continue

            if args.dry_run:
                log.info("DRY RUN enabled")

            success = await reboot_img(
                ip,
                dry_run=args.dry_run,
            )

            if not success:
                overall_success = False

        except Exception as exc:
            log.exception(
                "FAILED processing MAC %s: %s",
                supplied_mac,
                exc,
            )
            overall_success = False

    log.info("=" * 50)

    if overall_success:
        log.info("All device operations completed successfully")
    else:
        log.warning("One or more device operations failed")

    return overall_success



# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)

    except KeyboardInterrupt:
        log.warning("Operation cancelled by user")
        sys.exit(1)
