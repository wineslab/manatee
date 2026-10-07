# Real-RAN validation of the A/B switch

This folder runs the A/B control-authority switch on the real O-RAN control
path:

```
xDevSM PRB-control xApps → RMR → OSC E2Term → E2 → srsRAN gNB → ZMQ → srsUE
```

The core is Open5GS. Everything runs on one k3s cluster.

## RAN

The RAN uses the `simulated-ran-e2e` testbed configuration (Open5GS core,
srsRAN gNB, GNU Radio ZMQ bridge, srsUE). `simulated-ran-e2e.patch` holds
the changes needed on our cluster:

- **E2Term port:** e2term SCTP is reached on NodePort 32222 (36422 upstream).
- **MongoDB volume:** the Open5GS MongoDB hostPath PV is pinned to the
  control-plane node.
- **UE configs:** the namespaces in `ue.conf` and `ue-gnu.conf` are fixed
  (`srsue`/`srsran` → `simran-ue`/`simran-ran`).

The working copy also converts every file to LF line endings. The Windows
checkout had CRLF, which breaks `setup.sh` inside the init containers.

Other setup steps on our cluster:

- **Node labels:** the control-plane node gets `core=true ran=true ue=true
  primary=true`.
- **Tooling:** use kustomize v5 with Helm 3.11.2 (`~/.local/bin/helm3`, as
  pinned in `VERSIONS.md`):
  ```
  kustomize build --enable-helm --helm-command ~/.local/bin/helm3
  ```
  The snap Helm 4 lacks `helm version -c`.
- **inotify:** set `fs.inotify.max_user_instances=1024` with `sysctl -w`
  (not persistent). The xApp framework fails with `EMFILE` on a busy node.

## RIC fixes

- **Routing Manager:** it had lost the E2Term registration. E2Term and its
  gNB association were re-posted with `/ric/v1/handles/e2t` and
  `associate-ran-to-e2t`.
- **xApp Manager restarts:** restart xApps with scale 0 → 1, never with a
  rolling restart. During a rolling restart the old pod deregisters the xApp
  name after the new pod has registered it.

## xApps

`prb-xapp.yaml.tpl` lays the image out like an xApp Manager onboarded xApp: the
pod hostname equals the xApp name and the Services are
`service-ricxapp-<name>-http` and `service-ricxapp-<name>-rmr`. It also sets:

- `RMR_SRC_ID=service-ricxapp-<name>-rmr.ricxapp`, which must match the sender
  in the Routing Manager routes;
- `DBAAS_SERVICE_HOST`/`DBAAS_SERVICE_PORT`, so the xApp can reach the R-NIB.

`rc_xapp_ab.py` is the upstream PRB-control xApp with the same setup and the
same `send()`, called every second instead of once. It logs every send and
acknowledgement. Its options:

- `--call-process-id ""`: srsRAN rejects a RIC Call Process ID it does not
  define.
- `-m -u 0`: srsRAN applies slice PRB quota per UE and needs a gNB-DU UE ID.

## Version matrix

| xApp | OAI gNB images (all published ones) | srsRAN (docker_srsran refactor_n5) |
|------|-------------------------------------|------------------------------------|
| 0.3.0-dev | RC decoder segfaults | RC decoder segfaults |
| 0.2.0-dev | decodes; slice PRB quota is supported only by `oai-custom`, which asserts on the request | **works** (Control Acknowledge, policy applied) |

## Switch

`ab_switch_real.sh` inserts a leading rule in the platform's
`ric-rmr-e2term-vs`: traffic with `sourceLabels xapp=<name>` goes to an empty
subset. A DestinationRule scoped to `app=prb-xapp` (`maxConnectionDuration:
1s`) completes the mechanism. The original VirtualService is restored after
every run. Back it up before the first run.

`MODE=none` runs the native RIC with no mechanism, and `MODE=nolife` runs the
route without the connection-lifetime bound.

## Results

Data is in `results/oib/{ab,ab-none,ab-nolife,ab-tput,ab-none-tput}`. Summarise it with
`analysis/oib_ab_summary.py`. The figure is `fig_e4_real_ran` from `analysis/plots.py`.
