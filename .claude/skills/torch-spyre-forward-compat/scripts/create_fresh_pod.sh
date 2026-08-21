#!/usr/bin/env bash
# Create a fresh Spyre-capable pod for a torch forward-compatibility trial.
#
# The whole point of this skill is that the trial happens in a pod that
# has never had torch-spyre installed against any previous torch. This
# script refuses to reuse an existing pod name so that every trial starts
# from a known-clean image state, and records the immutable image digest
# from the pod's containerStatus so the trial log can prove exactly which
# base image was used.
#
# Usage:
#   create_fresh_pod.sh --name POD_NAME [--namespace NS] [--image IMAGE]
#
# Defaults:
#   --namespace  a5-deepview
#   --image      us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest
#
# Requires:
#   KUBECONFIG   set to the dev-cluster kubeconfig
#   oc           on PATH; caller already logged in (oc whoami must succeed)
#
# Exit codes:
#   0 — pod is Ready; recipe printed
#   1 — a pod with that name already exists in the namespace (refuse to reuse)
#   2 — usage error
#   3 — oc whoami failed (not authenticated to the cluster)
#   4 — pod did not become Ready within the 5-minute wait
#   5 — could not read the immutable image digest from status

set -euo pipefail

POD_NAME=""
NAMESPACE="a5-deepview"
IMAGE="us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest"

usage() {
    cat >&2 <<EOF
usage: create_fresh_pod.sh --name POD_NAME [--namespace NS] [--image IMAGE]

  --name       (required) name of the pod to create; must not already exist
  --namespace  (optional) OpenShift namespace; default: a5-deepview
  --image      (optional) container image (tag or @sha256 digest); default:
               us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest

Requires KUBECONFIG set and oc on PATH.
EOF
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)
            POD_NAME="${2:-}"
            shift 2
            ;;
        --namespace)
            NAMESPACE="${2:-}"
            shift 2
            ;;
        --image)
            IMAGE="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage
            ;;
    esac
done

if [ -z "$POD_NAME" ]; then
    echo "FATAL: --name is required" >&2
    usage
fi

if ! command -v oc >/dev/null 2>&1; then
    echo "FATAL: oc not found on PATH" >&2
    exit 2
fi

if [ -z "${KUBECONFIG:-}" ]; then
    echo "FATAL: KUBECONFIG is not set" >&2
    exit 2
fi

# Step 1: verify oc auth (loud on failure).
if ! WHOAMI=$(oc whoami 2>&1); then
    echo "FATAL: oc whoami failed — not authenticated to the cluster" >&2
    echo "$WHOAMI" >&2
    exit 3
fi
echo "# authenticated as: $WHOAMI"
echo "# namespace:        $NAMESPACE"
echo "# pod name:         $POD_NAME"
echo "# image:            $IMAGE"

# Step 2: refuse to reuse. The whole point is that this pod has never
# had torch-spyre installed against any prior torch.
if oc get pod "$POD_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "FATAL: pod $NAMESPACE/$POD_NAME already exists" >&2
    echo "       delete it first (oc delete pod $POD_NAME -n $NAMESPACE)" >&2
    echo "       or pick a different --name; this skill refuses silent reuse" >&2
    exit 1
fi

# Step 3: apply the manifest.
# Modeled on the existing tdeshane-compiler-timing-dev-v2 spec:
#   - one Spyre PF via ibm.com/spyre_pf: 1
#   - imagePullPolicy: Always so --image tag resolves to today's digest
#   - imagePullSecrets so wxpe-cicd-internal pulls succeed
#   - schedulerName: spyre-scheduler routes to a Spyre-capable node
#   - env vars enable Spyre PF mode from python
#   - dev-shm sized for torch's shared-memory needs
#   - squad-shared-pvc mounts $HOME so tdeshane's tree/creds are there,
#     and mounts /etc/passwd from the .passwd subPath so `whoami` works
#     under an arbitrary UID
#   - command /usr/bin/pause keeps the pod alive for `oc exec`
echo "# applying pod manifest..."
oc apply -f - <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: ${POD_NAME}
  namespace: ${NAMESPACE}
  labels:
    purpose: forward-compat
    deployer: tdeshane
    version: v1
spec:
  schedulerName: spyre-scheduler
  imagePullSecrets:
    - name: tdeshane-wxpe-cicd-image-pull
  restartPolicy: Never
  containers:
    - name: dev
      image: ${IMAGE}
      imagePullPolicy: Always
      command: ["/usr/bin/pause"]
      workingDir: /home/tdeshane
      env:
        - name: HF_HOME
          value: /home/tdeshane
        - name: FLEX_COMPUTE
          value: SENTIENT
        - name: FLEX_DEVICE
          value: PF
        - name: TOKENIZERS_PARALLELISM
          value: "false"
        - name: AIU_SETUP_MULTI_AIU
          value: "1"
      resources:
        limits:
          ibm.com/spyre_pf: 1
        requests:
          ibm.com/spyre_pf: 1
      volumeMounts:
        - name: dev-shm
          mountPath: /dev/shm
        - name: squad-shared-pvc
          mountPath: /home/tdeshane
          subPath: tdeshane
        - name: squad-shared-pvc
          mountPath: /etc/passwd
          subPath: tdeshane/.passwd
  volumes:
    - name: dev-shm
      emptyDir:
        medium: Memory
        sizeLimit: 64Gi
    - name: squad-shared-pvc
      persistentVolumeClaim:
        claimName: squad-shared-pvc
YAML

# Step 4: wait for Ready with a 5-minute timeout.
echo "# waiting for pod Ready (timeout 5m)..."
if ! oc wait --for=condition=Ready \
        "pod/${POD_NAME}" \
        -n "${NAMESPACE}" \
        --timeout=5m; then
    echo "FATAL: pod ${NAMESPACE}/${POD_NAME} did not become Ready within 5m" >&2
    echo "       recent events:" >&2
    oc describe pod "${POD_NAME}" -n "${NAMESPACE}" 2>&1 | tail -40 >&2 || true
    exit 4
fi

# Step 5: record the immutable image digest.
# imageID looks like "docker-pullable://registry/repo@sha256:...". This
# is the resolved digest of what actually got pulled onto this node,
# regardless of what tag the caller passed on --image.
IMAGE_ID=$(oc get pod "${POD_NAME}" -n "${NAMESPACE}" \
    -o jsonpath='{.status.containerStatuses[0].imageID}' 2>/dev/null || true)

if [ -z "$IMAGE_ID" ]; then
    echo "FATAL: could not read status.containerStatuses[0].imageID" >&2
    exit 5
fi

echo
echo "# pod is Ready"
echo "# image_id (immutable):"
echo "$IMAGE_ID"
echo
echo "# exec in with:"
echo "oc exec -it ${POD_NAME} -n ${NAMESPACE} -- bash"
