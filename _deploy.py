import os, json, urllib.request

token = os.environ["RAILWAY_TOKEN"]
query = {
    "query": 'mutation { deploy(serviceId: "49942508-21ff-4b26-8bb2-e2079c249360", environmentId: "production") { id status } }'
}

req = urllib.request.Request(
    "https://backboard.railway.app/graphql/v2",
    data=json.dumps(query).encode(),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
)
resp = urllib.request.urlopen(req)
print(resp.read().decode())
