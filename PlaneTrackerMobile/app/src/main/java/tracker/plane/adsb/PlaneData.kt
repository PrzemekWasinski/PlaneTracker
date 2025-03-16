package tracker.plane.adsb

data class PlaneData(
    val planeModel: String,
    val airlineName: String,
    val registration: String,
    val spottedAt: String
)
