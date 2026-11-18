
# Allied Telesis iMG Reboot Utility

A Python utility for locating and rebooting Allied Telesis iMG devices by MAC address.

The script uses SNMP to retrieve the ARP table from an Arista core switch, identifies the IP address associated with each requested MAC address, and connects to the iMG using Telnet to initiate a reboot.

Multiple devices can be processed concurrently, with a live terminal dashboard showing progress and status.

## Features

- **SNMP ARP lookup:** Retrieves the Arista MAC and IP tables using SNMP v2c.
- **Batch processing:** Looks up all requested MAC addresses using only two SNMP walks per run.
- **MAC normalization:** Accepts colon-separated, hyphen-separated, dotted, or unseparated MAC addresses.
- **Connectivity verification:** Pings each device before attempting a Telnet connection.
- **Parallel execution:** Processes multiple iMG devices concurrently.
- **Telnet management:** Logs into the iMG and enters privileged mode.
- **Automated reboot:** Sends the reboot command and confirms the reboot.
- **Reboot verification:** Confirms the device goes offline and subsequently returns online.
- **Dry-run mode:** Tests connectivity and login without rebooting devices.
- **Live dashboard:** Displays MAC address, IP address, current status, and progress.
- **Logging:** Records detailed activity in `img_reboot.log`.

## Requirements

### Operating system

Linux

### Python

Python 3.9 or newer recommended.

### System utilities

The following utilities must be installed and available:

- `snmpwalk` (Net-SNMP)
- `ping`

On Debian/Ubuntu:

```bash
sudo apt update
sudo apt install snmp
sudo apt install iputils-ping
```

### Python packages

```bash
pip install telnetlib3 python-dotenv
```

## Installation

Clone the repository:

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
```

Enter the project directory:

```bash
cd Allied_Reboot
```

Install the Python dependencies:

```bash
pip install telnetlib3 python-dotenv
```

Create the environment configuration file:

```bash
nano .env
```

Add the configuration described below.

## Configuration

The script reads connection settings from a `.env` file.

Example:

```ini
# Arista Core Switch - SNMP
ARISTA_HOST=10.100.10.1
ARISTA_SNMP_VERSION=2c
ARISTA_SNMP_COMMUNITY=public

# Allied Telesis iMG Credentials
IMG_USERNAME=admin
IMG_PASSWORD=your_password
IMG_ENABLE_PASSWORD=

# Telnet Settings
TELNET_PORT=23
TIMEOUT=12
```

### Configuration variables

| Variable | Description | Default |
|---|---|---|
| `ARISTA_HOST` | Arista switch IP address | `10.100.10.1` |
| `ARISTA_SNMP_VERSION` | SNMP version | `2c` |
| `ARISTA_SNMP_COMMUNITY` | SNMP community string | `public` |
| `IMG_USERNAME` | iMG login username | `admin` |
| `IMG_PASSWORD` | iMG login password | None |
| `IMG_ENABLE_PASSWORD` | Privileged-mode password | Empty |
| `TELNET_PORT` | iMG Telnet port | `23` |
| `TIMEOUT` | General connection timeout | `12` |

**Security note:** The `.env` file contains credentials. Never commit it to GitHub.

Create or update `.gitignore`:

```gitignore
.env
*.log
__pycache__/
*.pyc
.venv/
venv/
```

## Usage

Run the script with one or more MAC addresses.

### Single device

```bash
python3 img_reboot.py 00:0C:25:2B:2B:29
```

### Multiple devices

```bash
python3 img_reboot.py \
00:0C:25:2B:2B:29 \
00:0C:25:2B:2B:30
```

### Dry-run mode

Dry-run mode performs the SNMP lookup, ping check, and Telnet login but does not reboot the device.

```bash
python3 img_reboot.py 00:0C:25:2B:2B:29 --dry-run
```

### Supported MAC formats

All of the following formats are accepted:

```text
00:0C:25:2B:2B:29
00-0C-25-2B-2B-29
000C.252B.2B29
000C252B2B29
```

## How It Works

The script follows this workflow:

1. **SNMP lookup**
   - Connects to the Arista core switch.
   - Retrieves the MAC address table and IP address table using two SNMP walks.
   - Matches the tables using their shared OID index.
   - Builds a local MAC-to-IP dictionary.

2. **MAC address matching**
   - Normalizes each supplied MAC address.
   - Searches the local ARP dictionary.
   - Reports an error if no matching ARP entry exists.

3. **Ping verification**
   - Pings the discovered IP address.
   - Skips devices that do not respond.

4. **Telnet login**
   - Connects to the iMG.
   - Authenticates using the configured credentials.
   - Enters privileged mode.

5. **Reboot**
   - Sends the `reboot` command.
   - Waits for the confirmation prompt.
   - Sends `y`.
   - Waits for the device to acknowledge the reboot.

6. **Reboot verification**
   - Waits for the device to stop responding to ping.
   - Waits for the device to return online.
   - Reports success when connectivity is restored.

## SNMP Information

The script uses the standard MIB-II `ipNetToMediaTable`.

| OID | Description |
|---|---|
| `1.3.6.1.2.1.4.22.1.2` | MAC addresses |
| `1.3.6.1.2.1.4.22.1.3` | IP addresses |

Both tables use the same index structure:

```text
ifIndex.IP-address
```

The script matches entries using this shared index.

SNMP is queried only twice per execution, regardless of the number of requested devices.

**Important:** The ARP table is cache-based. Devices without a current matching ARP entry cannot be located by this method.

## Dashboard Statuses

| Status | Meaning |
|---|---|
| `PENDING` | Waiting to start |
| `SNMP LOOKUP` | Retrieving the Arista ARP table |
| `ARP LOOKUP` | Matching the requested MAC address |
| `IP NOT FOUND` | No matching SNMP entry |
| `PING CHECK` | Testing device connectivity |
| `SKIPPED` | Device did not respond to ping |
| `TELNET LOGIN` | Connecting to the iMG |
| `SENDING REBOOT` | Sending the reboot command |
| `WAITING OFFLINE` | Waiting for the device to stop responding |
| `REBOOTING` | Waiting for the device to return |
| `REBOOT VERIFIED` | Device successfully returned online |
| `DRY RUN SUCCESS` | Login successful; no reboot performed |
| `FAILED` | An error occurred during processing |

## Reboot Timeouts

| Operation | Timeout |
|---|---:|
| General Telnet prompt | 12 seconds |
| Reboot acknowledgment | 20 seconds |
| Wait for device offline | 60 seconds |
| Wait for device online | 300 seconds |

The device must first become unreachable and then respond again before the script reports a verified reboot.

## Logging

Detailed activity is recorded in:

```text
img_reboot.log
```

To monitor the log in another terminal:

```bash
tail -f img_reboot.log
```

The live dashboard is displayed in the main terminal.

## Troubleshooting

### MAC address not found

Possible causes:

- The device does not have a current ARP entry.
- The MAC address was entered incorrectly.
- The device is connected to a different network or routing interface.

Check the Arista ARP table:

```bash
snmpwalk -v2c -c public 10.100.10.1 \
1.3.6.1.2.1.4.22.1.2
```

### SNMP lookup fails

Verify SNMP connectivity:

```bash
snmpwalk -v2c -c public 10.100.10.1 \
1.3.6.1.2.1.1.5.0
```

The expected system name is:

```text
HQCore
```

### Ping fails

Verify the IP address is reachable:

```bash
ping <IP_ADDRESS>
```

The script intentionally skips devices that do not respond to its initial ping check.

### Telnet login fails

Verify:

- The iMG is reachable.
- Telnet is enabled.
- The username and password are correct.
- The `.env` file contains the correct credentials.

Review `img_reboot.log` for additional details.

## Project Structure

```text
Allied_Reboot/
│
├── img_reboot.py
├── README.md
├── .env
├── .gitignore
└── img_reboot.log
```

The `.env` and log files should not be committed to GitHub.

## Safety Notes

- Always test new changes using `--dry-run`.
- Verify the supplied MAC addresses before running an actual reboot.
- Devices must respond to the initial ping check.
- Reboots are performed concurrently, so avoid submitting large batches without considering network impact.
- Use a read-only SNMP community where possible.
- Keep credentials out of source code and version control.

## License

Internal network administration utility. 
