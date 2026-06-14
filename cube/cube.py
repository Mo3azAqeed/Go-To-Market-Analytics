from cube import config

@config("datasources")
def datasources(ctx):
    return {
        "bigquery": {
            "type": "bigquery",
            "project_id": ctx.env.get("GCP_PROJECT_ID"),
            "service_account": {
                "type": ctx.env.get("GCP_SERVICE_ACCOUNT_TYPE"),
                "project_id": ctx.env.get("GCP_PROJECT_ID"),
                "private_key_id": ctx.env.get("GCP_PRIVATE_KEY_ID"),
                "private_key": ctx.env.get("GCP_PRIVATE_KEY"),
                "client_email": ctx.env.get("GCP_CLIENT_EMAIL"),
                "client_id": ctx.env.get("GCP_CLIENT_ID"),
                "auth_uri": ctx.env.get("GCP_AUTH_URI"),
                "token_uri": ctx.env.get("GCP_TOKEN_URI"),
                "auth_provider_x509_cert_url": ctx.env.get("GCP_AUTH_PROVIDER_CERT_URL"),
                "client_x509_cert_url": ctx.env.get("GCP_CLIENT_CERT_URL"),
            },
            "location": "US",
        }
    }

@config("cubes")
def cubes():
    return [
        "cubes/sellers",
        "cubes/funnel",
        "cubes/orders",
        "cubes/partner_eligibility",
    ]
