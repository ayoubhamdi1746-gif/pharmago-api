import os, json, urllib.request

token = os.environ["RAILWAY_TOKEN"]

# Query latest deployments
query = {
    "query": """
    {
        deployments(serviceId: "49942508-21ff-4b26-8bb2-e2079c249360", first: 5) {
            edges {
                node {
                    id
                    status
                    createdAt
                    meta
                }
            }
        }
    }
    """
}

req = urllib.request.Request(
    "https://backboard.railway.app/graphql/v2",
    data=json.dumps(query).encode(),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
)
try:
    resp = urllib.request.urlopen(req)
    print(json.dumps(json.loads(resp.read()), indent=2))
except Exception as e:
    print(f"Error: {e}")
    if hasattr(e, 'read'):
        print(e.read().decode())
