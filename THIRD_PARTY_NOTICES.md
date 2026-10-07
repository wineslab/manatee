# Third-party notices

MANATEE is released under the MIT License (see `LICENSE`), except for the
file listed below.

## real-ran/rc_xapp_ab.py

Adapted from `prb_control_xapp/rc_xapp.py` of
[wineslab/xDevSM-xapps-examples](https://github.com/wineslab/xDevSM-xapps-examples),
licensed under the Apache License, Version 2.0
(<http://www.apache.org/licenses/LICENSE-2.0>). Modifications: the control
request is sent periodically instead of once; sends and acknowledgements are
logged; the RIC Call Process ID can be overridden; both 0.2.0-dev and
0.3.0-dev of the xDevSM framework are supported. The xDevSM framework itself
is not redistributed: it is used from the published container image
`angeloferaudo/prb-control-xapp`.

## Container images used (not redistributed)

O-RAN SC Near-RT RIC (j-release), Istio, Linkerd, Cilium, Tekton, ArgoCD, Argo
Rollouts, Gitea, Open5GS, srsRAN Project (`ghcr.io/herlesupreeth/docker_srsran`),
srsRAN 4G UE (`gradiant/srsran-4g`), OpenAirInterface. Each is subject to its
own license.
