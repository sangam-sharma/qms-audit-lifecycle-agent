import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { agentApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { Badge, EmptyState, ErrorBox, Loading } from "./ui";

function sourceLabel(source) {
    return `${source.entity} ${source.record_id} · ${source.field}: ${source.value}`;
}

function SourceList({ sources }) {
    if (!sources?.length) return null;
    return (
        <details className="ai-sources">
            <summary>Source references ({sources.length})</summary>
            <ul>
                {sources.map((source, index) => (
                    <li key={`${source.entity}-${source.record_id}-${source.field}-${index}`}>
                        <span className="mono">{sourceLabel(source)}</span>
                    </li>
                ))}
            </ul>
        </details>
    );
}

function AuditInsight({ audit }) {
    return (
        <article className="ai-audit">
            <div className="ai-audit-head">
                <div>
                    <span className="ai-rank">#{audit.rank}</span>
                    <strong className="mono">{audit.audit_code}</strong>
                    <span className="muted"> · {audit.project_name}</span>
                    <div className="muted small">{audit.status.replaceAll("_", " ")}</div>
                </div>
                <div className="ai-score" aria-label={`Priority score ${audit.priority_score}`}>
                    <strong>{audit.priority_score}</strong>
                    <span>priority points</span>
                </div>
            </div>

            {audit.priority_factors?.length > 0 && (
                <div className="ai-section">
                    <h4>Why this rank</h4>
                    <ul className="ai-list">
                        {audit.priority_factors.map((factor) => (
                            <li key={factor.code}>
                                <strong>+{factor.points}</strong> {factor.reason}
                                <SourceList sources={factor.source_refs} />
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {audit.facts?.length > 0 && (
                <div className="ai-section">
                    <h4>Findings</h4>
                    <ul className="ai-list">
                        {audit.facts.map((fact) => (
                            <li key={fact.id}>
                                <Badge value={fact.kind} /> <strong>{fact.title}</strong>
                                <p>{fact.detail}</p>
                                <SourceList sources={fact.source_refs} />
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {audit.recommendations?.length > 0 && (
                <div className="ai-section">
                    <h4>Recommendations</h4>
                    <ul className="ai-list">
                        {audit.recommendations.map((recommendation) => (
                            <li key={recommendation.id}>
                                <p>{recommendation.text}</p>
                                <SourceList sources={recommendation.source_refs} />
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {audit.unresolved_policies?.length > 0 && (
                <div className="ai-section">
                    <h4>Policy notes</h4>
                    <ul className="ai-list">
                        {audit.unresolved_policies.map((policy) => <li key={policy}>{policy}</li>)}
                    </ul>
                </div>
            )}

            <SourceList sources={audit.source_refs} />
        </article>
    );
}

export default function PortfolioAnalysis() {
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const { logout } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    const analyze = async () => {
        setLoading(true);
        setError("");
        try {
            const response = await agentApi.executeTask("Analyze all accessible audits");
            setResult(response);
        } catch (requestError) {
            const status = requestError.response?.status;
            if (status === 401) {
                logout();
                navigate("/login", { replace: true, state: { from: location } });
                return;
            }
            if (status === 403) {
                setError("Your account is not permitted to analyze these audits.");
            } else if (!requestError.response) {
                setError("Could not reach the audit agent. Check that the agent service is running and VITE_AGENT_API_BASE_URL is correct.");
            } else {
                setError("The audit agent could not complete the analysis. Please try again.");
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <section className="card ai-portfolio" aria-labelledby="ai-portfolio-title">
            <div className="card-head">
                <div>
                    <h2 id="ai-portfolio-title">AI audit analysis</h2>
                    <p className="muted small">Read-only portfolio ranking based on audits you can access.</p>
                </div>
                <button className="btn btn-primary" onClick={analyze} disabled={loading}>
                    {loading ? "Analyzing…" : result ? "Refresh analysis" : "Analyze all accessible audits"}
                </button>
            </div>

            {error && <ErrorBox message={error} />}
            {loading && <Loading label="Reviewing accessible audits…" />}
            {!loading && !result && !error && (
                <EmptyState title="Portfolio analysis is ready" text="Run an analysis to see ranked audits, findings, and recommended next steps." />
            )}
            {result && !loading && (
                <div className="ai-results" aria-live="polite">
                    <p className="ai-summary">{result.explanation}</p>
                    {result.portfolio_priority_method && (
                        <details className="ai-method">
                            <summary>How ranking works</summary>
                            <p>{result.portfolio_priority_method}</p>
                        </details>
                    )}
                    {result.ranked_audits?.length ? (
                        result.ranked_audits.map((audit) => <AuditInsight key={audit.audit_id} audit={audit} />)
                    ) : (
                        <EmptyState title="No accessible audits to rank" text="The agent returned no ranked audits for this account." />
                    )}
                    {result.portfolio_failures?.length > 0 && (
                        <div className="alert alert-error" role="status">
                            <div>
                                <strong>Some audits could not be analyzed</strong>
                                <ul className="ai-list">
                                    {result.portfolio_failures.map((failure) => (
                                        <li key={`${failure.audit_id}-${failure.reason}`}>
                                            <span className="mono">{failure.audit_code}</span>: {failure.message}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </section>
    );
}
