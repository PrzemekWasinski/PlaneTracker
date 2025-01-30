plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    id("com.google.gms.google-services") // Ensure you're using Google Services plugin
}

android {
    namespace = "com.example.planetracker"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.example.planetracker"
        minSdk = 31
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = "11"
    }
}

dependencies {
    // AndroidX libraries
    implementation(libs.androidx.core.ktx.v1120) // Ensure the correct version
    implementation(libs.androidx.appcompat.v161)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.material)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.espresso.core)

    // Firebase dependencies
    implementation("com.google.firebase:firebase-analytics:21.0.0") // Specify the version for Firebase Analytics
    implementation("com.google.firebase:firebase-firestore-ktx:24.10.0") // Correct version for Firestore
    implementation("com.google.firebase:firebase-auth-ktx:22.3.0") // Firebase Auth KTX

    // Networking and JSON
    implementation(libs.okhttp3.okhttp)
    implementation(libs.json)

    // Kotlin extensions and other libraries
    implementation(libs.kotlinx.coroutines.android)

    // Test dependencies
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
