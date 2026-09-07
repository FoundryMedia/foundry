# Foundry Wiki

Static documentation site for the Foundry platform orchestration toolkit.

## Development

```bash
cd wiki
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Build (Static Export)

```bash
npm run build
```

Output goes to `out/` — ready to deploy to S3 or any static host.

## Deployment

This site deploys as a static export to an S3 bucket behind CloudFront.
The infrastructure is managed separately from the platform service stacks.
