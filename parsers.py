"""Best-effort parser for 'show sip-ua register status' (CUBE/CUCM trunk
registration table). Layout is fixed-width, columns separated by runs of
'=' in the underline row, e.g.:

Tenant:  1
--------------------- Registrar-Index  1 ---------------------
Line                             peer      expires(sec) reg survival  P-Associ-URI
================================ ========= ============ === ========  ============
2397311t1                        -1         148          yes normal

If the output doesn't look like this table at all, returns None so the
caller can fall back to showing raw text only.
"""
import re

TENANT_RE = re.compile(r"^Tenant:\s*(\S+)")
REGISTRAR_RE = re.compile(r"Registrar-Index\s+(\S+)")
UNDERLINE_RE = re.compile(r"^[=\s]+$")

FIELDS = ["line", "peer", "expires_sec", "reg", "survival", "p_associ_uri"]


def _split_row(line):
    """Cisco right-pads numeric columns inconsistently, so exact column
    offsets from the '=' underline don't reliably line up with the data
    (e.g. 'yes' can start one char left of the 'reg' underline). Fields
    themselves never contain spaces, so whitespace-splitting is more
    robust than slicing by column position."""
    tokens = line.split()
    if len(tokens) < len(FIELDS) - 1:  # p_associ_uri may be omitted
        return None
    values = tokens[: len(FIELDS) - 1]
    values.append(tokens[len(FIELDS) - 1] if len(tokens) >= len(FIELDS) else "")
    return values


def parse_sip_ua_register_status(raw):
    if not raw or "Tenant:" not in raw:
        return None

    lines = raw.splitlines()
    rows = []
    tenant = None
    registrar_index = None

    i = 0
    while i < len(lines):
        line = lines[i]

        m = TENANT_RE.match(line.strip())
        if m:
            tenant = m.group(1)
            i += 1
            continue

        m = REGISTRAR_RE.search(line)
        if m:
            registrar_index = m.group(1)
            i += 1
            continue

        if line.strip() and UNDERLINE_RE.match(line.strip()) and "=" in line:
            i += 1
            # consume data rows until blank line / next section / EOF
            while i < len(lines) and lines[i].strip() and not TENANT_RE.match(lines[i].strip()):
                values = _split_row(lines[i])
                if values:
                    row = dict(zip(FIELDS, values))
                    row["tenant"] = tenant
                    row["registrar_index"] = registrar_index
                    row["registered"] = row.get("reg", "").lower() == "yes"
                    rows.append(row)
                i += 1
            continue

        i += 1

    return rows
