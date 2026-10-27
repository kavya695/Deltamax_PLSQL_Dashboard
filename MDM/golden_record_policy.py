class GoldenRecordPolicyEngine:

    def build_golden(self, cluster):
        return max(cluster, key=lambda r: r.trust_score)
