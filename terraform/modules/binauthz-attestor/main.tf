# Build attestor (D9): Container Analysis note + attestor in shr-build, HSM-backed EC P-256 signing key.
# Only builder@shr-build signs (access matrix: signerVerifier on the key, notes.attacher / occurrences.editor).
resource "google_kms_crypto_key" "signing" {
  name     = var.attestor.key.key
  key_ring = "projects/${var.attestor.project}/locations/${var.region}/keyRings/${var.attestor.key.key_ring}"
  purpose  = var.attestor.key.purpose
  version_template {
    algorithm        = var.attestor.key.algorithm
    protection_level = var.attestor.key.protection_level
  }
  lifecycle {
    prevent_destroy = true
  }
}

data "google_kms_crypto_key_version" "signing" {
  crypto_key = google_kms_crypto_key.signing.id
}

resource "google_container_analysis_note" "this" {
  project = var.attestor.project
  name    = var.attestor.note
  attestation_authority {
    hint {
      human_readable_name = "Built, scanned and signed by builder@shr-build"
    }
  }
}

resource "google_binary_authorization_attestor" "this" {
  project = var.attestor.project
  name    = var.attestor.name
  attestation_authority_note {
    note_reference = google_container_analysis_note.this.name
    public_keys {
      id = data.google_kms_crypto_key_version.signing.id
      pkix_public_key {
        public_key_pem      = data.google_kms_crypto_key_version.signing.public_key[0].pem
        signature_algorithm = data.google_kms_crypto_key_version.signing.public_key[0].algorithm
      }
    }
  }
}
