import 'package:flutter/material.dart';

class AppTheme {
  static const Color primaryRed = Color(0xFFE51F2A);
  static const Color deepRed = Color(0xFF8F0F18);
  static const Color black = Color(0xFF050505);
  static const Color surfaceBlack = Color(0xFF101010);
  static const Color cardColor = Color(0xFF191919);
  static const Color elevatedCard = Color(0xFF202020);
  static const Color borderRed = Color(0xFF3A1216);
  static const Color mutedText = Color(0xFF9B9B9B);

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      primaryColor: primaryRed,
      scaffoldBackgroundColor: black,
      canvasColor: black,
      cardTheme: const CardThemeData(
        color: cardColor,
        elevation: 3,
        margin: EdgeInsets.all(8),
        shadowColor: Color(0x99000000),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Color(0xFF0A0A0A),
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        titleTextStyle: TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.bold,
          color: Colors.white,
        ),
      ),
      colorScheme: const ColorScheme.dark(
        primary: primaryRed,
        secondary: deepRed,
        surface: cardColor,
        error: Color(0xFFFF4D55),
        onPrimary: Colors.white,
        onSecondary: Colors.white,
        onSurface: Colors.white,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: elevatedCard,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
        labelStyle: const TextStyle(color: mutedText),
        hintStyle: const TextStyle(color: mutedText),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: borderRed),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFF303030)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: primaryRed, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: primaryRed, width: 1.5),
        ),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: elevatedCard,
        elevation: 10,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: borderRed),
        ),
        textStyle: const TextStyle(color: Colors.white),
      ),
      dividerTheme: const DividerThemeData(
        color: Color(0xFF2D2D2D),
      ),
      listTileTheme: const ListTileThemeData(
        iconColor: primaryRed,
        textColor: Colors.white,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: primaryRed,
          foregroundColor: Colors.white,
          elevation: 2,
          padding: const EdgeInsets.symmetric(vertical: 16),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: primaryRed,
        ),
      ),
      iconTheme: const IconThemeData(
        color: Colors.white,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: primaryRed,
      ),
    );
  }
}
