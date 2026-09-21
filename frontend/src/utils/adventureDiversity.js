export function adventureSignature(data) {
  const places = data?.places ?? (data?.place ? [data.place] : []);
  return places
    .map((place) =>
      String(place.source_id ?? place.id ?? place.name ?? place.place_name ?? "")
        .trim()
        .toLowerCase(),
    )
    .filter(Boolean)
    .sort()
    .join("|");
}

export function rememberAdventure(history, signature, limit = 12) {
  if (!signature) return history;
  return [signature, ...history.filter((item) => item !== signature)].slice(
    0,
    limit,
  );
}
