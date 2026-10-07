# MANATEE

**M**esh **A**rchitecture for Radio Access **N**etwork **A**utomation and
**TE**sting **E**cosystems: a DevOps platform for the lifecycle management
and in-production testing of O-RAN xApps. It combines CI/CD pipelines with a
service mesh in front of the O-RAN SC Near-RT RIC.

This repository contains:

- the MANATEE pipelines;
- the test harness;
- the scripts for every experiment in the paper;
- the measured results and the analysis that produces the paper's figures
  and tables.

## What MANATEE does

| Flow | Mechanism | Where |
|------|-----------|-------|
| Canary deployment of xApps | Ansible pipeline. It shifts Istio weights step by step (10/25/50/75/100 %) and holds each step under a telemetry gate (error ratio and p95 latency from Prometheus). It rolls back automatically at the first violation. | `ansible/canary.yml`, `harness/gate.py` |
| A/B testing of xApps | Control authority over the E2 node is held by one variant at a time. The revoked xApp's outbound control connection is routed to an empty destination at its own sidecar. A bounded connection lifetime (`DestinationRule` `maxConnectionDuration`, 1 s) makes established RMR connections re-evaluated. | `k8s/`, `scripts/mesh.sh`, `real-ran/ab_switch_real.sh` |
| Comparison baselines | The native O-RAN SC / Kubernetes release mechanisms: xApp Manager undeploy-then-deploy, deploy-beside, and rolling update. | `scripts/e1_release.sh` |

## Repository layout

```
harness/      mock xApp (indications in, control out), load generator,
              E2-side control sink, telemetry gate, watchers
ansible/      MANATEE canary pipeline with health-gated rollback
charts/       Helm chart of the mock xApp (the same package for all mechanisms)
k8s/          namespace, routing, policy and job templates per data plane
engines/      the same canary on Tekton, ArgoCD (GitOps) and Argo Rollouts
scripts/      experiment drivers (E1-E5), data-plane abstraction, campaign runner
real-ran/     A/B switch with the xDevSM PRB-control xApp, OSC RIC and srsRAN
analysis/     per-experiment summaries, LaTeX tables, figures, notebook generator
results/      per-run measurements (per-second CSVs, events) and summaries
docs/         findings and caveats from the experiments
```

## Experiments

| ID | Question | Script |
|----|----------|--------|
| E1/E2 | A version change under load, MANATEE canary vs native release mechanisms, with a healthy and a faulty v2 | `scripts/e1_release.sh <mechanism> <none\|error\|delay> <rate> <rep>` |
| E3 | The same canary driven by Ansible, Tekton, ArgoCD (webhook and polling) and Argo Rollouts | `scripts/e3_engine.sh <engine> <none\|error> <rep>` |
| E4 | The A/B control-authority switch: overlap, gap and conflicting commands, including circuit-breaker variants | `scripts/e5_mesh.sh ab none <rep>`, `scripts/probe_cb_switch.sh` |
| E5 | Canary, A/B and overhead on Istio sidecar, Istio ambient, Linkerd and Cilium | `MESH=<mesh> scripts/e5_mesh.sh <canary\|ab\|overhead> <fault> <rep>` |
| Real RAN | The A/B switch with two xDevSM PRB-control xApps on the O-RAN SC RIC driving a srsRAN gNB with an attached UE | `real-ran/ab_switch_real.sh <rep>` (see `real-ran/README.md`) |

`scripts/campaign.sh` runs repetitions from a frozen copy of the tree.
Repetitions are the outer loop.

## Requirements

- **Cluster:** a Kubernetes cluster (k3s was used) with the O-RAN SC Near-RT
  RIC (j-release) and Istio 1.26. Prometheus is scraped every 5 s.
- **Tools:** Ansible core 2.17, Helm 3, `kubectl`, `envsubst`.
- **E3:** Tekton Pipelines v1.15, ArgoCD v3.5 and Argo Rollouts v1.10.
- **E5:** Linkerd (edge-26.9), Cilium 1.18 and Istio ambient, each on its own
  cluster.
- **Real-RAN validation:** Open5GS, srsRAN Project and srsUE over ZMQ. See
  `real-ran/README.md`.

## Quick start (E1, one run)

```bash
scripts/sync_and_build.sh <cluster-host>        # copy tree, build the harness image there
ssh <cluster-host> 'bash ~/manatee-rev/scripts/e1_release.sh manatee error 1000 1'
python3 analysis/e1_summary.py results/e1
```

## Reproducing the figures and tables

```bash
python3 analysis/e1_summary.py results/e1
python3 analysis/e3_summary.py results/e3
python3 analysis/e5_summary.py results/e5
python3 analysis/tables.py results tables/
(cd analysis && python3 e4_table.py ../results > ../tables/tab_e4_ab.tex)
python3 analysis/plots.py results figures/          # matplotlib + LaTeX
python3 analysis/make_notebook.py revision-plots.ipynb
```

Per-connection logs (`conns-*.csv`, about 94 MB) are not included. The
summaries use the per-second data, which is.

## Findings worth knowing before you build on this

See [`docs/findings.md`](docs/findings.md). In short:

- Istio circuit breakers cannot be opened on demand.
- Outlier detection does not eject a failing xApp on opaque TCP between
  sidecars.
- Neither Istio policies nor routing changes close RMR connections that are
  already established.
- The O-RAN SC Routing Manager routes RIC Control acknowledgements by message
  type only.

## Citation

S. Montebugnoli, L. Bonati, A. Sabbioni, L. Foschini, P. Bellavista, S. D'Oro,
M. Polese, T. Melodia, "MANATEE: A DevOps Platform for xApp Lifecycle
Management and Testing in Open RAN", under review.

## License

MIT (see `LICENSE`). `real-ran/rc_xapp_ab.py` is adapted from
wineslab/xDevSM-xapps-examples under Apache-2.0 (see `THIRD_PARTY_NOTICES.md`).
