# Acoustic Analyzer — build/push/deploy without sudo (via the in-cluster registry).
#
#   make deploy     build → push → restart the app pods   (the everyday command)
#   make push       build the image and push to the registry
#   make restart    just restart the pods (pull latest)
#   make configmaps refresh the engine + prompt ConfigMaps (no image needed)
#   make logs       tail the tool-service + chat logs
#
# One-time setup is in docs/DEPLOY-K3S.md (registry trust + Docker insecure-registries).

REG  ?= sachin-jetson.local:30500
IMG  ?= $(REG)/acoustic-tools:latest
NS   ?= acoustic

.PHONY: build push deploy restart configmaps logs registry-check

build:
	docker build -t $(IMG) .

push: build
	docker push $(IMG)

deploy: push restart

restart:
	kubectl -n $(NS) rollout restart deploy/acoustic-tools deploy/acoustic-chat
	kubectl -n $(NS) rollout status  deploy/acoustic-tools --timeout=120s

configmaps:
	kubectl -n $(NS) create configmap agent-shell    --from-file=agent_shell.py=src/agent_shell.py            --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NS) create configmap acoustic-agent --from-file=system.prompt=deploy/agents/acoustic.prompt --from-file=suggestions=deploy/agents/acoustic.suggestions --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(NS) rollout restart deploy/acoustic-chat

logs:
	kubectl -n $(NS) logs deploy/acoustic-tools --tail=20
	kubectl -n $(NS) logs deploy/acoustic-chat  --tail=20

registry-check:
	curl -s http://$(REG)/v2/_catalog || echo "  ! registry unreachable — is deploy/registry/registry.yaml applied + insecure-registries set?"
