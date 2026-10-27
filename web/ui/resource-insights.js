import { createElement as h, useEffect, useRef, useState } from "react";
import { topologyFromEvidence, securityFromEvidence } from "../resource-insights.js";
import { maskAccountIds } from "../presentation.js";

const text = (language, ko, en) => language === "en" ? en : ko;
const columns = { internet_gateway: 0, vpc: 1, subnet: 2, security_group: 2,
  route_table: 3, nat_gateway: 3, vpc_endpoint: 3, ec2: 3, rds: 3, ebs: 4 };
const checkNames = {
  sg_no_public_ssh: ["SSH 공개 접근 제한", "Restrict public SSH"],
  sg_no_public_rdp: ["RDP 공개 접근 제한", "Restrict public RDP"],
  sg_no_public_all_traffic: ["전체 트래픽 공개 제한", "Restrict unrestricted public traffic"],
  ebs_encrypted: ["EBS 암호화", "EBS encryption"],
  ecr_encrypted: ["ECR 암호화", "ECR encryption"],
  ecr_immutable_tags: ["ECR 태그 불변성", "ECR immutable tags"],
  ecr_scan_on_push: ["ECR push 스캔 설정", "ECR scan-on-push setting"],
  rds_encrypted: ["RDS 암호화", "RDS encryption"],
  rds_not_public: ["RDS 비공개 설정", "RDS private access"],
  s3_encrypted: ["S3 암호화", "S3 encryption"],
  s3_encryption_enabled: ["S3 암호화", "S3 encryption"],
  s3_public_access_block: ["S3 공개 접근 차단", "S3 public access block"],
  s3_bucket_public_access_block: ["S3 공개 접근 차단", "S3 public access block"],
  s3_policy_not_public: ["S3 정책의 공개 접근", "S3 policy public access"],
  s3_bucket_policy_not_public: ["S3 정책의 비공개 설정", "S3 private bucket policy"],
  s3_versioning: ["S3 버전 관리", "S3 versioning"],
  s3_versioning_enabled: ["S3 버전 관리", "S3 versioning"],
  dynamodb_encrypted: ["DynamoDB 암호화", "DynamoDB encryption"],
  dynamodb_encryption_enabled: ["DynamoDB 암호화", "DynamoDB encryption"],
  dynamodb_pitr: ["DynamoDB 시점 복구", "DynamoDB point-in-time recovery"],
  dynamodb_point_in_time_recovery: ["DynamoDB 시점 복구", "DynamoDB point-in-time recovery"],
  elasticache_encryption_at_rest: ["캐시 저장 암호화", "Cache encryption at rest"],
  elasticache_encryption_in_transit: ["캐시 전송 암호화", "Cache encryption in transit"],
  opensearch_encrypted: ["OpenSearch 암호화", "OpenSearch encryption"],
  opensearch_encryption_at_rest: ["OpenSearch 암호화", "OpenSearch encryption"],
  opensearch_node_encryption: ["OpenSearch 노드 간 암호화", "OpenSearch node-to-node encryption"],
  opensearch_node_to_node_encryption: ["OpenSearch 노드 간 암호화", "OpenSearch node-to-node encryption"],
  opensearch_https: ["OpenSearch HTTPS", "OpenSearch HTTPS"],
  opensearch_https_required: ["OpenSearch HTTPS", "OpenSearch HTTPS"],
  opensearch_advanced_security_enabled: ["OpenSearch 세부 접근 제어", "OpenSearch fine-grained access control"],
  msk_encryption_at_rest: ["MSK 저장 암호화", "MSK encryption at rest"],
  msk_client_tls_only: ["MSK 클라이언트 TLS", "MSK client TLS"],
  msk_in_cluster_encryption: ["MSK 클러스터 내부 암호화", "MSK intra-cluster encryption"],
  msk_unauthenticated_access_disabled: ["MSK 비인증 접근 차단", "MSK unauthenticated access disabled"],
};

function Graph({ graph, language, accounts }) {
  const container = useRef(null);
  const [width, setWidth] = useState(700);
  const [zoom, setZoom] = useState(1);
  const [selectedId, setSelected] = useState(null);
  const selected = graph.nodes.find((node) => node.id === selectedId);
  useEffect(() => {
    const element = container.current;
    const observer = new ResizeObserver(() => setWidth(Math.max(280, element.clientWidth)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const rows = {};
  const positions = new Map(graph.nodes.map((node) => {
    const column = columns[node.kind] ?? 3;
    const row = rows[column] || 0;
    rows[column] = row + 1;
    return [node.id, { x: 24 + column * 212, y: 20 + row * 86 }];
  }));
  const viewWidth = 220 + Math.max(1, ...Object.keys(rows).map(Number)) * 212;
  const viewHeight = Math.max(140, Math.max(1, ...Object.values(rows)) * 86 + 28);
  const display = (value) => maskAccountIds(String(value ?? ""), accounts, { strict: true });
  return h("div", null,
    h("div", { className: "graph-tools" },
      h("span", null, text(language, `리소스 ${graph.nodes.length}개`, `${graph.nodes.length} resources`)),
      h("button", { type: "button", className: "button secondary", onClick: () => setZoom(Math.min(2.5, zoom + .25)) }, "+"),
      h("button", { type: "button", className: "button secondary", onClick: () => setZoom(Math.max(.75, zoom - .25)) }, "−"),
      h("button", { type: "button", className: "button secondary", onClick: () => { setZoom(1); setSelected(null); } },
        text(language, "맞춤", "Fit"))),
    h("div", { className: "graph-scroll", ref: container },
      h("svg", { role: "img", "aria-label": text(language, "관측한 AWS 리소스 관계도", "Observed AWS resource relationships"),
        viewBox: `0 0 ${viewWidth} ${viewHeight}`, width: width * zoom, height: Math.max(180, viewHeight * width / viewWidth * zoom) },
      h("g", { className: "graph-edges" }, ...graph.edges.map((edge) => {
        const from = positions.get(edge.source), to = positions.get(edge.target);
        return h("path", { key: edge.id, d: `M${from.x + 176},${from.y + 28} C${from.x + 200},${from.y + 28} ${to.x - 24},${to.y + 28} ${to.x},${to.y + 28}` });
      })),
      h("g", null, ...graph.nodes.map((node) => {
        const position = positions.get(node.id);
        const activate = () => setSelected(node.id);
        const label = display(node.name || node.id);
        return h("g", { key: node.id, className: `graph-node kind-${node.kind}`, transform: `translate(${position.x} ${position.y})`,
          tabIndex: 0, role: "button", "aria-label": `${node.kind}: ${display(node.id)}`, onClick: activate,
          onKeyDown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); } } },
          h("rect", { width: 176, height: 58, rx: 7 }),
          h("text", { x: 10, y: 18, className: "graph-kind" }, node.kind.replaceAll("_", " ")),
          h("text", { x: 10, y: 39 }, label.length > 23 ? label.slice(0, 20) + "…" : label),
          h("title", null, `${node.kind}: ${display(node.id)}`));
      })))),
    selected ? h("pre", { className: "graph-selected" }, display(JSON.stringify(selected, null, 2))) : null);
}

export function ResourceInsights({ evidence, language = "ko", accounts = [] }) {
  const graph = topologyFromEvidence(evidence);
  const security = securityFromEvidence(evidence);
  const showGraph = evidence.some((result) => result.tool === "get_vpc_topology") && graph.nodes.length > 0;
  if (!showGraph && !security.checks.length) return null;
  return h("div", { className: "resource-insights" },
    showGraph ? h("section", { className: "insight-panel" },
      h("h2", null, text(language, "리소스 관계도", "Resource relationships")),
      h("p", { className: "insight-note" }, text(language,
        "조회한 구성 관계입니다. 실제 통신 가능 여부를 검사한 결과는 아닙니다.",
        "Observed configuration references. Network reachability has not been tested.")),
      graph.partial ? h("p", { className: "coverage-note" }, text(language,
        "일부 리소스나 관계가 조회되지 않았습니다.", "Some resources or relationships were not returned.")) : null,
      h(Graph, { graph, language, accounts })) : null,
    security.checks.length ? h("section", { className: "insight-panel" },
      h("h2", null, text(language, "보안 구성 점검", "Security configuration checks")),
      h("p", { className: "insight-note" }, text(language,
        "조회한 구성에 대한 점검입니다. 취약점이나 전체 보안 수준을 확정하지 않습니다.",
        "Checks of observed configuration, not a vulnerability or overall security verdict.")),
      security.partial ? h("p", { className: "coverage-note" }, text(language,
        "조회 범위와 오류를 함께 확인하세요.", "Review the query scope and errors.")) : null,
      h("div", { className: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ...[text(language, "리소스", "Resource"), text(language, "점검", "Check"), text(language, "결과", "Result")].map((value) => h("th", { key: value }, value)))),
        h("tbody", null, ...security.checks.map((check) => h("tr", { key: check.key },
          h("td", null, maskAccountIds(check.resource_id || check.service, accounts, { strict: true })),
          h("td", null, checkNames[check.check_id]?.[language === "en" ? 1 : 0] || check.check_id),
          h("td", { className: `security-${check.status}` },
            ({ pass: text(language, "기준 충족", "Meets rule"), fail: text(language, "확인 필요", "Review"), unknown: text(language, "미확인", "Unknown") })[check.status]))))))) : null);
}
