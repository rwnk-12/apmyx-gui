from backend.shared.folders import blocked_folder_hint

INTERCEPTED = ("self-signed certificate in certificate chain", "self signed certificate in certificate chain")
UNVERIFIED = ("CERTIFICATE_VERIFY_FAILED", "certificate verify failed", "SSLCertVerificationError")


def certificate_hint(message):
    lowered = message.lower()
    if any(marker in lowered for marker in INTERCEPTED):
        return ("Something on this computer or network replaced Apple's security certificate, usually antivirus "
                "HTTPS scanning, a VPN or a network filter. Allow apmyx and Python in that program, or turn off "
                "its HTTPS scanning for apple.com, then try again.")
    if any(marker.lower() in lowered for marker in UNVERIFIED):
        return ("apmyx couldn't verify Apple's security certificate. Check that this computer's date and time are "
                "correct and that no antivirus, VPN or network filter is scanning HTTPS, then try again.")
    return ""


def explain(message):
    hints = [hint for hint in (blocked_folder_hint(message), certificate_hint(message)) if hint]
    return " ".join([message, *hints]) if hints else message
