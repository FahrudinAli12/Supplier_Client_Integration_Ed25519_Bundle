"""Generate one Ed25519 key pair for a registered Supplier gateway device.

Run once on the Supplier backend workstation. Store the PRIVATE key only in
backend/.env. Register the PUBLIC key in the Client Supabase device_keys table.
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private_key = Ed25519PrivateKey.generate()
private_hex = private_key.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
).hex()
public_hex = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
).hex()

print("CLIENT_SUPPLIER_PRIVATE_KEY_HEX=" + private_hex)
print("PUBLIC_KEY_ED25519_HEX=" + public_hex)
print("\nSimpan private key hanya di backend/.env Supplier. Jangan kirim ke Client atau commit ke Git.")
print("Salin public key ke SUPPLIER_DEVICE_SETUP_TEMPLATE.sql di project Supabase Client.")
