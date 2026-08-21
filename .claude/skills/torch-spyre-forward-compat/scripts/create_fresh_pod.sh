#!/usr/bin/env bash
# Create a fresh Spyre-capable pod for a torch forward-compatibility trial.
#
# The point of this skill is that the trial happens in a pod that has
# never had torch-spyre installed against any previous torch. This
# script refuses to reuse an existing pod name so that every trial
# starts from a known-clean image state, and records the immutable
# image digest from the pod's containerStatus so the trial log can
# prove exactly which base image was used.
#
# Usage:
#   create_fresh_pod.sh --name POD_NAME
#                       [--namespace NS]
#                       [--image IMAGE_TAG_OR_DIGEST]
#                       [--digest FROM_EXISTING_POD]
#                       [--prefer-node NODE_NAME]
#                       [--pvc CLAIM_NAME]
#                       [--image-pull-secret SECRET_NAME]
#
# Image resolution:
#   1. If --digest is given, --image is ignored and the pod uses the
#      exact digest sha256:... from that source (which may be a pod
#      name — the script will read its imageID). This is the strongest
#      form because it eliminates :latest tag drift.
#   2. Otherwise --image is used verbatim. It may be a tag or a
#      digest form (registry/repo@sha256:...).
#
# Cache-hit scheduling:
#   --prefer-node adds preferredDuringSchedulingIgnoredDuringExecution
#   affinity so the scheduler prefers a node where the image is already
#   cached. Empirical observation on dev.spyre: an uncached
#   torch-aiu-runtime-dev pull on a fresh node can hang for >60 min
#   without surfaced errors. Prefer a node that has an existing pod
#   running the same image.
#
# Defaults:
#   --namespace  a5-deepview
#   --image      us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest
#   --pvc        a5-deepview
#   --image-pull-secret  tdeshane-wxpe-cicd-image-pull
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
#   6 — --digest source pod does not exist or has no imageID

set -euo pipefail

POD_NAME=""
NAMESPACE="a5-deepview"
IMAGE="us.icr.io/wxpe-cicd-internal/amd64/torch-aiu-runtime-dev:latest"
DIGEST_FROM=""
PREFER_NODE=""
PVC_CLAIM="a5-deepview"
PULL_SECRET="tdeshane-wxpe-cicd-image-pull"

usage() {
    sed -n '2,52p' "$0" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --name)              POD_NAME="${2:-}"; shift 2 ;;
        --namespace)         NAMESPACE="${2:-}"; shift 2 ;;
        --image)             IMAGE="${2:-}"; shift 2 ;;
        --digest)            DIGEST_FROM="${2:-}"; shift 2 ;;
        --prefer-node)       PREFER_NODE="${2:-}"; shift 2 ;;
        --pvc)               PVC_CLAIM="${2:-}"; shift 2 ;;
        --image-pull-secret) PULL_SECRET="${2:-}"; shift 2 ;;
        -h|--help)           usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
done

[ -z "$POD_NAME" ] && { echo "FATAL: --name is required" >&2; usage; }
command -v oc >/dev/null 2>&1 || { echo "FATAL: oc not on PATH" >&2; exit 2; }
[ -n "${KUBECONFIG:-}" ] || { echo "FATAL: KUBECONFIG not set" >&2; exit 2; }

if ! WHOAMI=$(oc whoami 2>&1); then
    echo "FATAL: oc whoami failed — not authenticated" >&2
    echo "$WHOAMI" >&2; exit 3
fi

# Step 1: resolve --digest into a concrete image ref
if [ -n "$DIGEST_FROM" ]; then
    if oc get pod "$DIGEST_FROM" -n "$NAMESPACE" >/dev/null 2>&1; then
        DIGEST_IMG=$(oc get pod "$DIGEST_FROM" -n "$NAMESPACE" \
            -o jsonpath='{.status.containerStatuses[0].imageID}' 2>/dev/null || true)
        if [ -z "$DIGEST_IMG" ]; then
            echo "FATAL: pod $DIGEST_FROM exists but has no imageID (still ContainerCreating?)" >&2
            exit 6
        fi
        IMAGE="$DIGEST_IMG"
        echo "# --digest resolved from pod $DIGEST_FROM: $IMAGE"
    else
        if [[ "$DIGEST_FROM" == *"@sha256:"* ]]; then
            IMAGE="$DIGEST_FROM"
            echo "# --digest used verbatim: $IMAGE"
        else
            echo "FATAL: --digest '$DIGEST_FROM' is not a pod in $NAMESPACE nor a sha256 ref" >&2
            exit 6
        fi
    fi
fi

IMAGE_PULL_POLICY="Always"
if [[ "$IMAGE" == *"@sha256:"* ]]; then
    IMAGE_PULL_POLICY="IfNotPresent"
fi

echo "# authenticated as:  $WHOAMI"
echo "# namespace:         $NAMESPACE"
echo "# pod name:          $POD_NAME"
echo "# image:             $IMAGE"
echo "# imagePullPolicy:   $IMAGE_PULL_POLICY"
echo "# imagePullSecret:   $PULL_SECRET"
echo "# pvc claim:         $PVC_CLAIM"
[ -n "$PREFER_NODE" ] && echo "# prefer-node:      $PREFER_NODE"

# Step 2: refuse to reuse
if oc get pod "$POD_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "FATAL: pod $NAMESPACE/$POD_NAME already exists" >&2
    echo "       delete it first (oc delete pod $POD_NAME -n $NAMESPACE)" >&2
    echo "       or pick a different --name; this skill refuses silent reuse" >&2
    exit 1
fi

# Step 3: build the affinity stanza if --prefer-node given
AFFINITY_STANZA=""
if [ -n "$PREFER_NODE" ]; then
    AFFINITY_STANZA="
  affinity:
    nodeAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          preference:
            matchExpressions:
              - key: kubernetes.io/hostname
                operator: In
                values: [\"${PREFER_NODE}\"]"
fi

# Step 4: apply the manifest
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
    termination-mode: manual
    version: v2
spec:
  serviceAccountName: default
  schedulerName: spyre-scheduler
  imagePullSecrets:
    - name: ${PULL_SECRET}${AFFINITY_STANZA}
  containers:
    - name: app
      image: ${IMAGE}
      imagePullPolicy: ${IMAGE_PULL_POLICY}
      command: ["/usr/bin/sleep", "infinity"]
      workingDir: /home/tdeshane
      env:
        - { name: HF_HOME, value: /home/tdeshane }
        - { name: FLEX_COMPUTE, value: SENTIENT }
        - { name: FLEX_DEVICE, value: PF }
        - { name: TOKENIZERS_PARALLELISM, value: "false" }
        - { name: AIU_SETUP_MULTI_AIU, value: "1" }
      resources:
        requests: { ibm.com/spyre_pf: "1" }
        limits:   { ibm.com/spyre_pf: "1" }
      volumeMounts:
        - { name: dev-shm, mountPath: /dev/shm }
        - { name: squad-shared-pvc, mountPath: /home/tdeshane, subPath: tdeshane }
        - { name: squad-shared-pvc, mountPath: /etc/passwd, subPath: tdeshane/.passwd }
  securityContext:
    seccompProfile: { type: RuntimeDefault }
  volumes:
    - name: dev-shm
      emptyDir: { medium: Memory, sizeLimit: 64Gi }
    - name: squad-shared-pvc
      persistentVolumeClaim: { claimName: ${PVC_CLAIM} }
YAML

# Step 5: wait for Ready
echo "# waiting for pod Ready (timeout 5m)..."
if ! oc wait --for=condition=Ready \
        "pod/${POD_NAME}" -n "${NAMESPACE}" --timeout=5m; then
    echo "FATAL: pod ${NAMESPACE}/${POD_NAME} did not become Ready in 5m" >&2
    echo "       If image is uncached on the assigned node, an uncached pull can" >&2
    echo "       hang >60 min. Consider --prefer-node NODE where the image is" >&2
    echo "       already running, or --digest to pin to a byte-exact ref." >&2
    echo "       recent events:" >&2
    oc describe pod "${POD_NAME}" -n "${NAMESPACE}" 2>&1 | tail -40 >&2 || true
    exit 4
fi

# Step 6: record the immutable image digest
IMAGE_ID=$(oc get pod "${POD_NAME}" -n "${NAMESPACE}" \
    -o jsonpath='{.status.containerStatuses[0].imageID}' 2>/dev/null || true)
NODE=$(oc get pod "${POD_NAME}" -n "${NAMESPACE}" \
    -o jsonpath='{.spec.nodeName}' 2>/dev/null || true)

if [ -z "$IMAGE_ID" ]; then
    echo "FATAL: could not read status.containerStatuses[0].imageID" >&2
    exit 5
fi

echo
echo "# pod is Ready"
echo "# node:              $NODE"
echo "# image_id:          $IMAGE_ID"
echo
echo "# exec in with:"
echo "oc exec -it ${POD_NAME} -n ${NAMESPACE} -- bash"
echo
echo "# for byte-exact repro in a follow-up run, pass:"
echo "#   --image \"$IMAGE_ID\"   or   --digest ${POD_NAME}"
