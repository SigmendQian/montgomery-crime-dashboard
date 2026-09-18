import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data_service import DAY_ORDER

PROFILE_ORDER = ["High", "Mix", "Low/Mid"]
PROFILE_COLORS = {"High": "#4C78A8", "Mix": "#E7A54B", "Low/Mid": "#D56563"}


def incident_counts(df, groups):
    return df.groupby(groups, observed=True)["Incident ID"].nunique().rename("Incidents").reset_index()


def comparison_table(df, group, baseline, comparison):
    if baseline == comparison:
        raise ValueError("Choose different years.")
    counts = df.loc[df["Year"].isin([baseline, comparison])].groupby([group, "Year"], observed=True)["Incident ID"].nunique().unstack(fill_value=0)
    counts = counts.reindex(columns=[baseline, comparison], fill_value=0)
    counts.columns = ["Baseline", "Comparison"]
    result = counts.reset_index()
    result["Change"] = result["Comparison"] - result["Baseline"]
    result["Change (%)"] = 100 * result["Change"].div(result["Baseline"].replace(0, np.nan))
    return result.sort_values("Change", ascending=False).reset_index(drop=True)


def change_chart(table, group, title, limit=None):
    rows = table.copy()
    if limit and len(rows) > limit:
        half = limit // 2
        positive = rows.loc[rows["Change"].gt(0)].nlargest(half, "Change")
        negative = rows.loc[rows["Change"].lt(0)].nsmallest(half, "Change")
        rows = pd.concat([positive, negative]).drop_duplicates(subset=[group])
    rows = rows.sort_values("Change")
    rows["Direction"] = np.where(rows["Change"].ge(0), "Increase", "Decrease")
    rows["Label"] = [f"{int(n):+,}" for n in rows["Change"]]
    fig = px.bar(rows, x="Change", y=group, orientation="h", color="Direction", text="Label", custom_data=["Baseline", "Comparison", "Change (%)"], color_discrete_map={"Increase": "#CC5A52", "Decrease": "#4089A1"}, title=title)
    fig.update_traces(cliponaxis=False, textposition="outside", hovertemplate="%{y}<br>Baseline: %{customdata[0]:,}<br>Comparison: %{customdata[1]:,}<br>Change: %{x:+,}<br>Change (%): %{customdata[2]:.1f}<extra></extra>")
    fig.update_layout(height=max(350, 29 * len(rows) + 120), showlegend=False, margin=dict(l=15, r=65, t=60, b=30))
    fig.update_xaxes(title="Change in distinct incidents", zeroline=True)
    fig.update_yaxes(title=None, type="category")
    return fig


def time_heatmap(df, dispatch=False):
    if dispatch:
        valid = df.loc[df["Dispatch Date / Time"].notna(), ["Incident ID", "Dispatch Date / Time"]].copy()
        valid["Day"] = valid["Dispatch Date / Time"].dt.dayofweek
        valid["Hour"] = valid["Dispatch Date / Time"].dt.hour
    else:
        valid = df[["Incident ID", "Day_of_Week_Number", "Hour"]].rename(columns={"Day_of_Week_Number": "Day"})
    heat = valid.groupby(["Day", "Hour"], observed=True)["Incident ID"].nunique().unstack(fill_value=0).reindex(index=range(7), columns=range(24), fill_value=0).fillna(0)
    fig = go.Figure(go.Heatmap(z=heat.to_numpy(), x=list(range(24)), y=DAY_ORDER, colorscale="YlOrRd", colorbar=dict(title="Incidents"), hovertemplate="%{y}, %{x}:00–:59<br>Distinct incidents: %{z}<extra></extra>"))
    fig.update_layout(height=360, margin=dict(t=25, b=45), xaxis_title="Dispatch hour" if dispatch else "Occurrence / start hour")
    fig.update_xaxes(dtick=2)
    fig.update_yaxes(autorange="reversed")
    return fig


def case_takeaway(baseline_count, comparison_count, districts):
    delta = comparison_count - baseline_count
    up = districts.loc[districts["Change"].gt(0)]
    down = districts.loc[districts["Change"].lt(0)]
    if delta < 0 and not up.empty:
        return "The countywide decline masks increases in some police districts. The geographic distribution changed; county totals alone do not describe every district's experience."
    if delta > 0 and not down.empty:
        return "The countywide increase coexists with declines in some police districts. The geographic distribution changed unevenly, so the aggregate trend is not universal."
    if delta == 0 and not up.empty and not down.empty:
        return "The county total is unchanged, while individual districts moved in opposite directions. Stable totals can conceal substantial local change."
    if delta < 0:
        return "The county total declined, and no included district increased in this comparison. The evidence does not support a claim that activity shifted toward growing districts."
    if delta > 0:
        return "The county total increased. Compare the district and ZIP changes to see how broadly that increase was distributed."
    return "The county total is unchanged. Read the detailed counts before interpreting changes in the geographic distribution."
