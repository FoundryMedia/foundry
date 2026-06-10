import { WikiLayout } from "@/components/WikiLayout";

export default function IacLayoutPage(): React.ReactElement {
  return (
    <WikiLayout title="IaC Layout" description="How infrastructure is split between foundry-iac and per-repo stacks.">
      <div className="prose-wiki max-w-3xl">
        <h1>IaC Layout</h1>
        <p>
          Foundry uses OpenTofu and splits infrastructure into two layers: a shared{" "}
          <strong>control plane</strong> with reusable modules in <code>foundry-iac</code>, and
          per-repo <strong>app-edge</strong> stacks in each service{"'"}s <code>ci/iac/</code>.
        </p>

        <h2>foundry-iac — shared modules + control plane</h2>
        <p>
          <code>foundry-iac</code> holds reusable OpenTofu modules and the control-plane stack that
          provisions the always-on platform (VPC, ECS cluster + Fargate services, RDS, ALB,
          CloudFront + WAF, bastion, OIDC roles). Module categories include:
        </p>
        <pre><code>{`modules/
  vpc/  ec2/  ssh-key/  security-group/
  ecs/ecs-cluster/  ecs/ecs-service/  ecr/  cloudmap/
  rds/  lambda/
  alb/  cloudfront/  waf/  acm/  route53/`}</code></pre>
        <p>
          The control-plane composition (e.g. <code>prod/</code>) wires these modules together,
          keeps its state in S3, and is applied independently of any single app.
        </p>

        <h2>Per-repo ci/iac — app edge</h2>
        <p>
          Each deployable repo carries its own OpenTofu stack under <code>ci/iac/&lt;stack&gt;</code>{" "}
          for the infrastructure unique to that app — typically a static site{"'"}s S3 bucket and
          CloudFront distribution. A typical stack:
        </p>
        <pre><code>{`ci/iac/<stack>/
  providers.tf      # aws + aws.us_east_1 (for CloudFront/ACM certs)
  backend.tf        # remote state
  bucket.tf         # S3 bucket
  certificate.tf    # ACM certificate
  cloudfront.tf     # CloudFront distribution
  dns.tf            # Route 53 records
  iam.tf            # the tofu-runner role CI assumes
  outputs.tf        # bucket_name, distribution_id, ...`}</code></pre>

        <h2>How they connect to a deploy</h2>
        <p>
          The <a href="/docs/manifest/central">central manifest</a> points each service at its
          app-edge stack via <code>deploy.iac.stackPath</code> and names the outputs to read
          (<code>bucketOutput</code>, <code>distributionIdOutput</code>). The{" "}
          <a href="/docs/deploy/orchestrator">orchestrator</a> plans/applies that stack (smart
          IaC), reads those outputs, and uses them to publish the build. The shared{" "}
          <code>foundry-iac</code> control plane is applied separately and consumed by the modules
          themselves.
        </p>
      </div>
    </WikiLayout>
  );
}
