import { AgentCoreApplication, type AgentCoreApplicationProps } from '@aws/agentcore-cdk';
import { Stack, type StackProps } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends StackProps {
  /** Props for the AgentCore application, produced by transformAgentCoreJson from agentcore/agentcore.json. */
  application: AgentCoreApplicationProps;
}

// The models the agent may call: Haiku 4.5 by default, Sonnet 4.6 as the MODEL_ID fallback.
const ALLOWED_MODELS = ['anthropic.claude-haiku-4-5-20251001-v1:0', 'anthropic.claude-sonnet-4-6*'];

// Configuration bundles are a CLI feature this agent does not use.
const CONFIGURATION_BUNDLE_ACTIONS = [
  'bedrock-agentcore:CreateConfigurationBundle',
  'bedrock-agentcore:DeleteConfigurationBundle',
  'bedrock-agentcore:GetConfigurationBundle',
  'bedrock-agentcore:GetConfigurationBundleVersion',
  'bedrock-agentcore:ListConfigurationBundleVersions',
  'bedrock-agentcore:ListConfigurationBundles',
  'bedrock-agentcore:UpdateConfigurationBundle',
];

/**
 * The stack the AgentCore CLI deploys. Everything declared in agentcore/agentcore.json is
 * created by the AgentCoreApplication construct. Add your own resources below it and wire
 * them to your runtimes and harnesses through the application's accessors.
 */
export class AgentCoreStack extends Stack {
  public readonly application: AgentCoreApplication;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);
    this.application = new AgentCoreApplication(this, 'Application', props.application);
    this.restrictRuntimeRole(this.application.runtime('support_agent').role);
  }

  /** Explicit denies always override allows, so these narrow the CLI-generated runtime role. */
  private restrictRuntimeRole(role: iam.IRole): void {
    role.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: 'OnlyTheAgentModels',
        effect: iam.Effect.DENY,
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        // "us." inference profiles route to foundation models in several US regions.
        notResources: ALLOWED_MODELS.flatMap((model) => [
          `arn:aws:bedrock:*::foundation-model/${model}`,
          `arn:aws:bedrock:*:${this.account}:inference-profile/us.${model}`,
        ]),
      }),
    );
    // The agent never deletes long-term memory records; it only deletes its own events.
    role.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: 'NoMemoryRecordDeletes',
        effect: iam.Effect.DENY,
        actions: ['bedrock-agentcore:DeleteMemoryRecord'],
        resources: ['*'],
      }),
    );
    role.addToPrincipalPolicy(
      new iam.PolicyStatement({
        sid: 'NoConfigurationBundles',
        effect: iam.Effect.DENY,
        actions: CONFIGURATION_BUNDLE_ACTIONS,
        resources: ['*'],
      }),
    );
  }
}
