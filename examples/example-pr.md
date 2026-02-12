# Example Pull Request

This shows what a typical PR created by Remote Dev Bot looks like.

---

## PR Title

**Add dark mode support to the settings page**

(The title is automatically derived from the issue title)

## PR Body

```markdown
This PR was created by [OpenHands](https://github.com/OpenHands/OpenHands) to resolve #42.

## Changes

- Added dark mode toggle component in `src/components/Settings.tsx`
- Created dark mode CSS variables in `styles/tokens.css`
- Added localStorage persistence for theme preference
- Applied theme class to document body on load

## Testing

- Toggle switches between light and dark themes
- Preference persists across page reloads
- All existing styles remain unchanged in light mode

Fixes #42
```

---

## What the PR Contains

The agent typically:
- Makes focused changes to address the issue
- Follows existing code patterns in the repository
- Includes a summary of what was changed

## Iterating on the PR

If the PR needs changes, comment on it with feedback:

```
/agent

The toggle should be in the header, not the settings page. Also add a keyboard shortcut (Ctrl+D).
```

The agent will run again, read your feedback, and push additional commits to the same PR.

---

## Tips for Good Results

1. **Be specific in issues** — Clear requirements lead to better implementations
2. **Include context** — Mention relevant files, patterns, or constraints
3. **Use the right model** — Complex tasks benefit from `/agent-claude-large`
4. **Iterate with feedback** — Comment `/agent` with specific feedback to refine the PR
